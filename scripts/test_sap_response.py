"""Actual ADK runner: terminal SAP results require no post-tool model call."""
import base64
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from google.adk.agents import Agent
from google.adk.artifacts.in_memory_artifact_service import InMemoryArtifactService
from google.adk.models.base_llm import BaseLlm
from google.adk.models.llm_request import LlmRequest
from google.adk.models.llm_response import LlmResponse
from google.adk.runners import Runner
from google.adk.sessions.in_memory_session_service import InMemorySessionService
from google.genai import types
from pydantic import PrivateAttr

from smart_agents import invoice_tools
from smart_agents.sap_tools import sap_query_purchase_order
from smart_agents.sap_response import sap_result_before_model_callback, format_sap_result
from smart_agents.artifact_callbacks import deliver_session_artifacts_callback, _embed_data_uris_in_text

ORDER = '4500071250'
PNG = base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+a0i8AAAAASUVORK5CYII=')
INVOICE = {'purchase_order': ORDER, 'purchase_orders': [{'value':ORDER, 'evidence':'PO '+ORDER}],
    'supplier': {'value':'Harbor Components Demo Ltd.', 'evidence':'Harbor Components Demo Ltd.'},
    'invoice_number': {'value':'DEMO-INV-002', 'evidence':'Invoice number DEMO-INV-002'},
    'currency': {'value':'USD', 'evidence':'Currency USD'},
    'total_amount': {'value':'250.00', 'evidence':'TOTAL USD 250.00'}}


class ToolModel(BaseLlm):
    _calls: int = PrivateAttr(default=0)
    tool_name: str
    tool_args: dict = {}
    allow_second: bool = False
    async def generate_content_async(self, llm_request, stream=False):
        self._calls += 1
        if self._calls == 1:
            part=types.Part(function_call=types.FunctionCall(name=self.tool_name, args=self.tool_args))
        else:
            if not self.allow_second:
                raise AssertionError('Unexpected model call after completed SAP tool')
            part=types.Part(text='ordinary tool answer')
        yield LlmResponse(content=types.Content(role='model',parts=[part]))


class SapResponseTests(unittest.IsolatedAsyncioTestCase):
    async def run_tool(self, name, recognized=None, worker_result=None):
        tools={'sap_query_purchase_order':sap_query_purchase_order,
            'sap_query_from_invoice':invoice_tools.sap_query_from_invoice,
            'sap_query_recognized_invoice':invoice_tools.sap_query_recognized_invoice}
        model=ToolModel(model='offline',tool_name=name,tool_args={'purchase_order':ORDER} if name=='sap_query_purchase_order' else {})
        agent=Agent(name='sap_response',model=model,tools=[tools[name]],
            before_model_callback=sap_result_before_model_callback,
            after_agent_callback=deliver_session_artifacts_callback)
        sessions=InMemorySessionService()
        session=await sessions.create_session(app_name='sap_response',user_id='one',state={
            invoice_tools.PENDING_KEY:{'principal':'adk:one','invoice':INVOICE}})
        runner=Runner(agent=agent,app_name='sap_response',session_service=sessions,artifact_service=InMemoryArtifactService())
        recognized=recognized or {'ok':True,'can_query_sap':True,'data':INVOICE}
        worker_result=worker_result or {'ok':True,'purchase_order':ORDER,'mode':'computer-use','screenshot_base64':base64.b64encode(PNG).decode()}
        with patch('smart_agents.sap_tools._request',AsyncMock(return_value=worker_result)) as request, \
             patch.object(invoice_tools,'recognize_invoice_part',AsyncMock(return_value=recognized)):
            events=[e async for e in runner.run_async(user_id='one',session_id=session.id,new_message=types.Content(role='user',parts=[
                types.Part(text='识别发票并查询SAP'),types.Part.from_bytes(data=b'pdf-fixture',mime_type='application/pdf')]))]
        texts='\n'.join(p.text for e in events if e.content and e.content.role=='model' for p in e.content.parts or [] if p.text)
        return model, texts, events, request

    async def test_all_three_sap_paths_skip_post_tool_model_and_deliver_one_image(self):
        for name in ('sap_query_purchase_order','sap_query_from_invoice','sap_query_recognized_invoice'):
            with self.subTest(name=name):
                model,text,events,_=await self.run_tool(name)
                self.assertEqual(model._calls,1)
                self.assertIn(ORDER,text)
                self.assertEqual(text.count('data:image/png;base64,'),1)
                self.assertIn('未自动核验',text)
                self.assertFalse(any(p.inline_data for e in events if e.content for p in e.content.parts or []))
                if name!='sap_query_purchase_order':
                    self.assertIn('Harbor Components Demo Ltd.',text)
                    self.assertIn('Invoice number DEMO-INV-002',text)
                    self.assertIn('PO '+ORDER,text)

    async def test_missing_po_returns_grounded_fields_without_sap_or_second_model(self):
        data={**INVOICE,'purchase_order':None,'purchase_orders':[]}
        model,text,_,request=await self.run_tool('sap_query_from_invoice',recognized={
            'ok':True,'can_query_sap':False,'wait_user':True,'data':data,'message':'缺少明确PO，请补充采购订单号。'})
        self.assertEqual(model._calls,1)
        request.assert_not_awaited()
        self.assertIn('查询尚未完成',text)
        self.assertIn('请补充采购订单号',text)
        self.assertNotIn('data:image',text)

    async def test_worker_failure_is_not_reported_as_query_success(self):
        model,text,_,_=await self.run_tool('sap_query_from_invoice',worker_result={
            'ok':False,'wait_user':True,'error':{'code':'SAP_TIMEOUT','message':'本机查询超时'}})
        self.assertEqual(model._calls,1)
        self.assertIn('本机查询超时',text)
        self.assertNotIn('已查询 SAP',text)

    async def test_non_sap_tool_retains_ordinary_model_summary(self):
        async def ordinary_tool(): return {'ok':True}
        model=ToolModel(model='offline',tool_name='ordinary_tool',allow_second=True)
        sessions=InMemorySessionService();session=await sessions.create_session(app_name='other',user_id='one')
        agent=Agent(name='other',model=model,tools=[ordinary_tool],before_model_callback=sap_result_before_model_callback)
        runner=Runner(agent=agent,app_name='other',session_service=sessions)
        events=[e async for e in runner.run_async(user_id='one',session_id=session.id,new_message=types.Content(role='user',parts=[types.Part(text='other')]))]
        self.assertEqual(model._calls,2)
        self.assertTrue(any(p.text=='ordinary tool answer' for e in events if e.content for p in e.content.parts or []))

    async def test_new_user_message_and_parallel_other_tool_are_not_shortcircuited(self):
        part=types.Part(function_response=types.FunctionResponse(name='sap_query_purchase_order',response={'ok':True,'purchase_order':ORDER}))
        callback=SimpleNamespace(state={},invocation_id='test')
        old=types.Content(role='user',parts=[part]);new=types.Content(role='user',parts=[types.Part(text='下一件事')])
        self.assertIsNone(await sap_result_before_model_callback(callback,LlmRequest(contents=[old,new])))
        other=types.Part(function_response=types.FunctionResponse(name='other',response={'ok':True}))
        self.assertIsNone(await sap_result_before_model_callback(callback,LlmRequest(contents=[types.Content(role='user',parts=[part,other])])) )

    async def test_artifact_failure_returns_answer_without_hanging_or_claiming_image(self):
        callback=SimpleNamespace(state={},invocation_id='test',load_artifact=AsyncMock(side_effect=TimeoutError()))
        part=types.Part(function_response=types.FunctionResponse(name='sap_query_purchase_order',response={
            'ok':True,'purchase_order':ORDER,'artifacts':[{'filename':'sap.png','version':0,'mime_type':'image/png'}]}))
        response=await sap_result_before_model_callback(callback,LlmRequest(contents=[types.Content(role='user',parts=[part])]))
        self.assertIn('截图暂未交付',response.content.parts[0].text)
        self.assertNotIn('data:image',response.content.parts[0].text)

    def test_untrusted_fields_are_escaped_and_sap_data_is_not_labelled_invoice(self):
        text=format_sap_result({'ok':False,'invoice':{'supplier':{'value':'<img>|`bad`','evidence':'<script>bad</script>'}}})
        self.assertNotIn('<img>',text)
        self.assertNotIn('<script>',text)
        self.assertIn('\\|',text)
        self.assertNotIn('发票识别结果',format_sap_result({'ok':True,'purchase_order':ORDER,'data':{'supplier':'Carbon Tec'}}))

    def test_split_or_bare_filename_reference_becomes_canonical_image_markdown(self):
        filename='sap-order-4500071250.png'
        uri='data:image/png;base64,'+base64.b64encode(PNG).decode()
        images=[(filename,'image/png',uri)]
        for original in (f'![{filename}]\n({filename})', f'截图：({filename})', '[Image]'):
            with self.subTest(original=original):
                output=_embed_data_uris_in_text(original,images)
                self.assertIn(f'![{filename}]({uri})',output)
                self.assertEqual(output.count(uri),1)

if __name__=='__main__': unittest.main()
