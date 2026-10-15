"""Encrypted, per-user authentication state. Never store screenshots or passwords."""
import hashlib
import json

from cryptography.fernet import Fernet
from google.api_core.exceptions import NotFound


class CloudStateStore:
    def __init__(self, bucket, encryption_key: str, *, prefix='sap-auth'):
        if prefix not in {'sap-auth', 'orangehrm-auth'}:
            raise ValueError('Unknown browser state namespace')
        self.bucket = bucket
        self.cipher = Fernet(encryption_key.encode())
        self.prefix = prefix

    def _blob(self, user):
        return self.bucket.blob(self.prefix + '/' + hashlib.sha256(user.encode()).hexdigest() + '.enc')

    def load(self, user):
        blob = self._blob(user)
        try:
            blob.reload(timeout=10, retry=None)
        except NotFound:
            return None, 0
        generation = int(blob.generation)
        data = blob.download_as_bytes(if_generation_match=generation, timeout=10, retry=None)
        if len(data) > 4_000_000:
            raise ValueError('Authentication state too large')
        state = json.loads(self.cipher.decrypt(data))
        if not isinstance(state, dict) or not isinstance(state.get('cookies'), list):
            raise ValueError('Invalid authentication state')
        return state, generation

    def save(self, user, state, generation):
        raw = json.dumps(state).encode()
        if len(raw) > 3_000_000:
            raise ValueError('Authentication state too large')
        blob = self._blob(user)
        # A stale revision must not overwrite a newer browser's authentication state.
        blob.upload_from_string(self.cipher.encrypt(raw), content_type='application/octet-stream',
                                if_generation_match=generation, timeout=10, retry=None)
        return int(blob.generation)
