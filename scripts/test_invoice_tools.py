"""Invoice contracts: native attachments, PO ambiguity, continuation, ADK context."""
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from google.genai import types
from google.adk.agents import Agent
from google.adk.models.base_llm import BaseLlm
from google.adk.models.llm_response import LlmResponse
from google.adk.runners import Runner
from google.adk.sessions.in_memory_session_service import InMemorySessionService
from pydantic import PrivateAttr
from smart_agents import invoice_tools as invoice

ORDER = "4500071250"


def extraction(*orders):
    return invoice.InvoiceExtraction(purchase_orders=[invoice.InvoiceField(value=order,
        evidence="Purchase Order: " + order) for order in orders],
        invoice_number=invoice.InvoiceField(value="9900000001", evidence="Invoice No: 9900000001"))


def context(*parts):
    return SimpleNamespace(user_id="one", state={},
        user_content=types.Content(role="user", parts=list(parts)))


class GroundingTests(unittest.TestCase):
    def test_unique_po_dedup_and_evidence(self):
        fields = invoice.normalize_invoice(extraction(ORDER, ORDER))
        self.assertEqual(fields["purchase_order"], ORDER)
        self.assertEqual(len(fields["purchase_orders"]), 1)

    def test_invoice_number_cannot_be_po(self):
        doc = extraction()
        doc.purchase_orders = [invoice.InvoiceField(value=ORDER, evidence="Invoice No: " + ORDER)]
        self.assertIsNone(invoice.normalize_invoice(doc)["purchase_order"])

    def test_multiple_pos_do_not_pick_first(self):
        self.assertIsNone(invoice.normalize_invoice(extraction(ORDER, "4500000001"))["purchase_order"])

    def test_unsupported_number_or_missing_evidence_is_discarded(self):
        doc = extraction("123", "٤٥٠٠٠٧١٢٥٠")
        doc.purchase_orders.append(invoice.InvoiceField(value=ORDER, evidence="PO: 4500000001"))
        doc.supplier = invoice.InvoiceField(value="Invented", evidence="Supplier: Carbon Tec")
        fields = invoice.normalize_invoice(doc)
        self.assertEqual(fields["purchase_orders"], [])
        self.assertIsNone(fields["supplier"]["value"])

    def test_current_gcs_and_inline_attachment(self):
        ctx = context(types.Part(text="invoice"), types.Part.from_uri(
            file_uri="gs://media/invoice.PDF", mime_type="application/pdf"))
        self.assertEqual(invoice._attachment(ctx, None).file_data.file_uri, "gs://media/invoice.PDF")
        ctx = context(types.Part.from_bytes(data=b"image", mime_type="image/jpg"))
        self.assertEqual(invoice._attachment(ctx, 0).inline_data.mime_type, "image/jpeg")

    def test_arbitrary_url_unsupported_or_empty_attachment_rejected(self):
        for part in (types.Part.from_uri(file_uri="https://example.com/invoice.pdf", mime_type="application/pdf"),
                     types.Part.from_bytes(data=b"x", mime_type="text/plain"),
                     types.Part.from_bytes(data=b"", mime_type="application/pdf")):
            with self.assertRaises(ValueError):
                invoice._attachment(context(part), None)

    def test_multi_attachment_requires_selection_and_valid_index(self):
        part = types.Part.from_bytes(data=b"pdf", mime_type="application/pdf")
        ctx = context(part, part)
        for index in (None, -1, 2, True):
            with self.assertRaises(ValueError):
                invoice._attachment(ctx, index)
        self.assertEqual(invoice._attachment(ctx, 1).inline_data.data, b"pdf")


class WorkflowTests(unittest.IsolatedAsyncioTestCase):
    async def test_native_pdf_input_and_schema(self):
        generate = AsyncMock(return_value=SimpleNamespace(parsed=extraction(ORDER)))
        client = SimpleNamespace(aio=SimpleNamespace(models=SimpleNamespace(generate_content=generate)))
        part = types.Part.from_bytes(data=b"pdf", mime_type="application/pdf")
        result = await invoice.recognize_invoice_part(part, client=client)
        self.assertTrue(result["can_query_sap"])
        call = generate.call_args.kwargs
        self.assertEqual(call["contents"][0].parts[1].inline_data.data, b"pdf")
        self.assertIs(call["config"].response_schema, invoice.InvoiceExtraction)

    async def test_invalid_model_output_is_error(self):
        generate = AsyncMock(return_value=SimpleNamespace(parsed=None, text="not json"))
        client = SimpleNamespace(aio=SimpleNamespace(models=SimpleNamespace(generate_content=generate)))
        self.assertFalse((await invoice.recognize_invoice_part(types.Part(text="x"), client=client))["ok"])

    async def test_ambiguous_or_missing_po_does_not_query(self):
        for orders in ((), (ORDER, "4500000001")):
            result = {"ok": True, "data": invoice.normalize_invoice(extraction(*orders)), "can_query_sap": False}
            with patch.object(invoice, "recognize_invoice_part", AsyncMock(return_value=result)), \
                 patch.object(invoice, "sap_query_purchase_order", AsyncMock()) as sap:
                response = await invoice.sap_query_from_invoice(context(types.Part.from_bytes(data=b"pdf", mime_type="application/pdf")))
            self.assertFalse(response["can_query_sap"])
            sap.assert_not_awaited()

    async def test_failure_clears_old_invoice(self):
        ctx = context()
        ctx.state[invoice.PENDING_KEY] = {"principal": "adk:one", "invoice": {"purchase_order": ORDER}}
        self.assertFalse((await invoice.invoice_extract(ctx))["ok"])
        self.assertIsNone(ctx.state[invoice.PENDING_KEY])

    async def test_login_then_continue_with_identity_binding(self):
        ctx = context(types.Part.from_bytes(data=b"pdf", mime_type="application/pdf"))
        recognized = {"ok": True, "can_query_sap": True, "data": invoice.normalize_invoice(extraction(ORDER))}
        with patch.object(invoice, "recognize_invoice_part", AsyncMock(return_value=recognized)) as ocr, \
             patch.object(invoice, "sap_query_purchase_order", AsyncMock(side_effect=[
                 {"ok": False, "error": {"code": "LOGIN_REQUIRED"}},
                 {"ok": True, "artifacts": [{"filename": "result.png"}]}])) as sap:
            first = await invoice.sap_query_from_invoice(ctx)
            self.assertEqual(first["next_action"], "sap_query_recognized_invoice")
            second = await invoice.sap_query_recognized_invoice(ctx)
            self.assertTrue(second["ok"])
            ocr.assert_awaited_once()
            self.assertEqual(sap.await_count, 2)
            ctx.user_id = "other"
            self.assertFalse((await invoice.sap_query_recognized_invoice(ctx))["ok"])
            self.assertEqual(sap.await_count, 2)

    async def test_actual_adk_runner_preserves_native_tse_attachment(self):
        class Model(BaseLlm):
            _called: bool = PrivateAttr(default=False)
            async def generate_content_async(self, llm_request, stream=False):
                if not self._called:
                    self._called = True
                    part = types.Part(function_call=types.FunctionCall(name="sap_query_from_invoice", args={}))
                else:
                    part = types.Part(text="done")
                yield LlmResponse(content=types.Content(role="model", parts=[part]))

        agent = Agent(name="invoice_contract", model=Model(model="offline"), tools=[invoice.sap_query_from_invoice])
        sessions = InMemorySessionService()
        session = await sessions.create_session(app_name="invoice_contract", user_id="one", state={
            "tse_user_email": "owner@example.com", "tse_auth_source": "tse_app"})
        runner = Runner(app_name="invoice_contract", agent=agent, session_service=sessions)
        recognized = {"ok": True, "can_query_sap": True, "data": invoice.normalize_invoice(extraction(ORDER))}
        with patch.object(invoice, "recognize_invoice_part", AsyncMock(return_value=recognized)) as ocr, \
             patch.object(invoice, "sap_query_purchase_order", AsyncMock(return_value={"ok": True})) as sap:
            events = [event async for event in runner.run_async(user_id="one", session_id=session.id,
                new_message=types.Content(role="user", parts=[types.Part(text="查询附件采购单"),
                    types.Part.from_uri(file_uri="gs://media/invoice.pdf", mime_type="application/pdf")]))]
        self.assertEqual(ocr.call_args.args[0].file_data.file_uri, "gs://media/invoice.pdf")
        self.assertEqual(sap.call_args.args[0], ORDER)
        responses = [part.function_response.response for event in events if event.content
                     for part in event.content.parts if part.function_response]
        self.assertTrue(responses[0]["ok"])
        fresh = await sessions.get_session(app_name="invoice_contract", user_id="one", session_id=session.id)
        self.assertEqual(fresh.state[invoice.PENDING_KEY]["principal"], "tse:owner@example.com")


if __name__ == "__main__":
    unittest.main()
