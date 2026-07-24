import base64
import json
import sys
from types import SimpleNamespace
from typing import Any, cast

import pytest

from utils.browser import (
	_parse_linuxdo_oauth_payload,
	decode_browser_storage_state,
	launch_login_context,
	load_browser_login_settings,
	login_with_linuxdo_oauth,
)


def test_browser_login_settings_records_profile_persistence(monkeypatch, tmp_path):
	monkeypatch.setenv('CHECKIN_BROWSER_PROFILE_DIR', str(tmp_path))

	settings = load_browser_login_settings('Account 1', 'agentrouter', persist_profile=False)

	assert settings.persist_profile is False
	assert settings.profile_dir == tmp_path / 'agentrouter' / 'Account 1'


@pytest.mark.asyncio
async def test_launch_login_context_uses_persistent_context_when_enabled(monkeypatch, tmp_path):
	calls = {}
	context = SimpleNamespace()

	async def fake_launch_persistent_context_async(profile_dir, **kwargs):
		calls['profile_dir'] = profile_dir
		calls['kwargs'] = kwargs
		return context

	monkeypatch.setitem(
		sys.modules,
		'cloakbrowser',
		SimpleNamespace(launch_persistent_context_async=fake_launch_persistent_context_async),
	)

	settings = load_browser_login_settings('Account 1', 'anyrouter', persist_profile=True)
	settings = settings.__class__(
		headless=settings.headless,
		humanize=False,
		wait_timeout_ms=settings.wait_timeout_ms,
		profile_dir=tmp_path / 'profiles' / 'anyrouter' / 'Account 1',
		cloakbrowser_binary_path=settings.cloakbrowser_binary_path,
		persist_profile=settings.persist_profile,
	)

	result = await launch_login_context(settings)

	assert cast(Any, result) is context
	assert calls['profile_dir'] == str(settings.profile_dir)


@pytest.mark.asyncio
async def test_launch_login_context_closes_browser_for_ephemeral_context(monkeypatch, tmp_path):
	class FakeContext:
		def __init__(self):
			self.closed = False

		async def close(self):
			self.closed = True

	class FakeBrowser:
		def __init__(self):
			self.context = FakeContext()
			self.closed = False
			self.context_kwargs = {}
			self.launch_kwargs = {}

		async def new_context(self, **kwargs):
			self.context_kwargs = kwargs
			return self.context

		async def close(self):
			self.closed = True

	browser = FakeBrowser()

	async def fake_launch_async(**kwargs):
		browser.launch_kwargs = kwargs
		return browser

	monkeypatch.setitem(
		sys.modules,
		'cloakbrowser',
		SimpleNamespace(launch_async=fake_launch_async),
	)

	settings = load_browser_login_settings('Account 1', 'agentrouter', persist_profile=False)
	settings = settings.__class__(
		headless=settings.headless,
		humanize=False,
		wait_timeout_ms=settings.wait_timeout_ms,
		profile_dir=tmp_path / 'profiles' / 'agentrouter' / 'Account 1',
		cloakbrowser_binary_path=settings.cloakbrowser_binary_path,
		persist_profile=settings.persist_profile,
	)

	context = await launch_login_context(settings)
	await context.close()

	assert cast(Any, context).closed is True
	assert browser.closed is True
	assert not settings.profile_dir.exists()


def test_decode_browser_storage_state_accepts_base64_json():
	state = {'cookies': [{'name': 'session', 'value': 'secret'}], 'origins': []}
	encoded = base64.b64encode(json.dumps(state).encode()).decode()

	assert decode_browser_storage_state(encoded) == state


def test_parse_linuxdo_oauth_payload_returns_check_in_status():
	profile, checked_in = _parse_linuxdo_oauth_payload(
		{'success': True, 'data': {'id': 123, 'username': 'user', 'checked_in': True}}
	)

	assert profile['id'] == 123
	assert checked_in is True


@pytest.mark.asyncio
async def test_launch_login_context_passes_storage_state_to_ephemeral_context(monkeypatch, tmp_path):
	class FakeContext:
		async def close(self):
			return None

	class FakeBrowser:
		def __init__(self):
			self.context_kwargs = {}

		async def new_context(self, **kwargs):
			self.context_kwargs = kwargs
			return FakeContext()

		async def close(self):
			return None

	browser = FakeBrowser()

	async def fake_launch_async(**kwargs):
		return browser

	monkeypatch.setitem(sys.modules, 'cloakbrowser', SimpleNamespace(launch_async=fake_launch_async))
	settings = load_browser_login_settings('Account 1', 'agentrouter', persist_profile=False)
	state: dict[str, list[object]] = {'cookies': [], 'origins': []}

	context = await launch_login_context(settings, storage_state=state)
	await context.close()

	assert browser.context_kwargs['storage_state'] == state


@pytest.mark.asyncio
async def test_linuxdo_oauth_logs_out_before_processing_callback():
	class FakeResponse:
		url = 'https://agentrouter.org/api/oauth/linuxdo?code=code&state=state&mode=login'
		status = 200

		async def json(self):
			return {'success': True, 'data': {'id': 123, 'checked_in': True}}

	class FakeLocator:
		async def is_visible(self):
			return True

		async def scroll_into_view_if_needed(self):
			return None

		async def click(self, **kwargs):
			return None

		@property
		def first(self):
			return self

	class FakeContext:
		def __init__(self):
			self.listener = None
			self.request = FakeRequest(self)

		def on(self, event, listener):
			assert event == 'response'
			self.listener = listener

		def remove_listener(self, event, listener):
			assert event == 'response'
			assert listener is self.listener

	class FakeAPIResponse:
		def __init__(self, payload):
			self.payload = payload
			self.ok = True
			self.status = 200

		async def json(self):
			return self.payload

	class FakeRequest:
		def __init__(self, context):
			self.context = context

		async def get(self, url):
			if url.endswith('/api/status'):
				return FakeAPIResponse(
					{'success': True, 'data': {'linuxdo_oauth': True, 'linuxdo_client_id': 'client-id'}}
				)
			if '/api/oauth/state?mode=login' in url:
				return FakeAPIResponse({'success': True, 'data': 'oauth-state'})
			raise AssertionError(f'unexpected request: {url}')

	class FakePage:
		def __init__(self):
			self.context = FakeContext()
			self.visited = []

		async def goto(self, url, **kwargs):
			self.visited.append(url)
			if url.startswith('https://connect.linux.do/oauth2/authorize'):
				listener = self.context.listener
				assert listener is not None
				await listener(FakeResponse())

		async def wait_for_load_state(self, *args, **kwargs):
			return None

		def get_by_role(self, *args, **kwargs):
			return FakeLocator()

	page = FakePage()

	profile, checked_in = await login_with_linuxdo_oauth(cast(Any, page), 'https://agentrouter.org/login', 1_000)

	assert page.visited[0] == 'https://agentrouter.org/api/user/logout'
	assert page.visited[1].startswith('https://connect.linux.do/oauth2/authorize?')
	assert 'client_id=client-id' in page.visited[1]
	assert 'state=oauth-state' in page.visited[1]
	assert profile['id'] == 123
	assert checked_in is True
