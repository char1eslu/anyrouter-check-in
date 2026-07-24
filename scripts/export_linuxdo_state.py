#!/usr/bin/env python3
"""Interactively export a Linux.do Playwright storage state for GitHub Actions."""

import asyncio
import base64
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from utils.browser import launch_login_context, load_browser_login_settings

OUTPUT_PATH = Path('.linuxdo-storage-state.b64')


async def main() -> None:
	os.environ['CHECKIN_HEADLESS'] = 'false'
	settings = load_browser_login_settings('LinuxDO Export', 'agentrouter', persist_profile=False)
	context = await launch_login_context(settings)
	try:
		page = await context.new_page()
		await page.goto('https://connect.linux.do/', wait_until='domcontentloaded', timeout=60_000)
		input('请在打开的浏览器中完成 Linux.do 登录，确认已登录后回到终端按 Enter：')

		state = await context.storage_state()
		linuxdo_cookies = [
			cookie for cookie in state.get('cookies', []) if str(cookie.get('domain', '')).endswith('linux.do')
		]
		if not linuxdo_cookies:
			raise RuntimeError('未检测到 Linux.do cookie，请确认浏览器中已经登录')

		payload = json.dumps(state, ensure_ascii=True, separators=(',', ':')).encode('utf-8')
		OUTPUT_PATH.write_text(base64.b64encode(payload).decode('ascii'), encoding='ascii')
		OUTPUT_PATH.chmod(0o600)
		print(f'已写入 {OUTPUT_PATH}；该文件包含登录凭据，请勿提交到 Git。')
	finally:
		await context.close()


if __name__ == '__main__':
	asyncio.run(main())
