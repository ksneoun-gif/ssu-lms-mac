"""Run in ordinary PowerShell: verify installed LMS over MCP, then repair its launcher."""
import asyncio
import json
import os
from pathlib import Path
import sys
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

import argparse
from install_windows import configure, configuration
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--plugin-root', type=Path)
args = parser.parse_args()
cache = Path.home() / '.codex/plugins/cache/ssu-lms-github/ssu-lms'
candidates = [p.parent.parent for p in cache.glob('*/.codex-plugin/plugin.json')]
PLUGIN = args.plugin_root or max(candidates, key=lambda p: p.stat().st_mtime, default=None)
if PLUGIN is None:
    raise SystemExit('No installed LMS plugin found; pass --plugin-root.')

async def verify():
    params = StdioServerParameters(command=sys.executable, args=['-u', str(PLUGIN/'server.py')], cwd=str(PLUGIN), env=dict(os.environ))
    async with stdio_client(params) as (reader, writer):
        async with ClientSession(reader, writer) as client:
            await asyncio.wait_for(client.initialize(), 30)
            tools = {t.name for t in (await client.list_tools()).tools}
            print('MCP_CONNECTED', len(tools), flush=True)
            if 'diagnose_materials' not in tools:
                raise RuntimeError('Updated material-resolution tool is missing; old server is still loaded.')
            async def call(name, arguments):
                result = await asyncio.wait_for(client.call_tool(name, arguments), 45)
                if result.isError:
                    raise RuntimeError(name + ' failed; inspect the local server error.')
                data = getattr(result, 'structuredContent', None)
                if data is not None:
                    return data.get('result', data) if isinstance(data, dict) else data
                return json.loads(next(c.text for c in result.content if c.type == 'text'))
            auth = await call('auth_status', {})
            print('AUTH', json.dumps(auth, ensure_ascii=True), flush=True)
            if auth.get('authenticated') is not True or auth.get('verified_live') is not True:
                raise RuntimeError('Live school authentication did not pass.')
            if auth.get('server_version') != '0.3.4':
                raise RuntimeError('Expected server version 0.3.4.')
            courses = await call('list_courses', {})
            if not isinstance(courses, list):
                raise RuntimeError('Unexpected course response.')
            print('COURSES', json.dumps(courses, ensure_ascii=True), flush=True)
            sample = None
            for course in courses:
                rows = await call('list_materials', {'course_id': course['course_id']})
                print('MATERIAL_COUNT', course['course_id'], len(rows), flush=True)
                if not rows:
                    diagnostic = await call('diagnose_materials', {'course_id':course['course_id']})
                    print('MATERIAL_DIAGNOSIS', course['course_id'], diagnostic['canvas_lookup_status'],
                          'unresolved', len(diagnostic['unresolved_items']), flush=True)
                if rows and sample is None:
                    sample = (course['course_id'], rows[0])
            if sample:
                course_id, row = sample
                staged = await call('stage_material', {'course_id':course_id, 'content_id':row['content_id'], 'week':row.get('week','')})
                try:
                    print('DOWNLOAD_OK', json.dumps({'filename':staged['filename'],'bytes':staged['bytes']}, ensure_ascii=True), flush=True)
                finally:
                    cleanup = await call('delete_staged_material', {'staging_id':staged['staging_id']})
                    if cleanup.get('deleted') is not True:
                        raise RuntimeError('Temporary file cleanup was not confirmed.')
                    print('CLEANUP_OK', flush=True)
            else:
                print('DOWNLOAD_SKIPPED_NO_OPEN_FILES', flush=True)
            if courses:
                weekly = await call('list_weekly_content', {'course_id':courses[0]['course_id']})
                print('WEEKLY_CONTENT', json.dumps(weekly, ensure_ascii=True), flush=True)
            print('TRANSCRIPTION_NOT_STARTED: choose a verified lecture after reviewing weekly content.', flush=True)
    configure(PLUGIN, configuration(PLUGIN, sys.executable))
    print('VERIFIED_AND_LAUNCHER_UPDATED. Restart Codex once to load the verified transport.', flush=True)

if __name__=='__main__':
    try:
        asyncio.run(verify())
    except Exception as error:
        print('VERIFICATION_FAILED',type(error).__name__,flush=True)
        print('No launcher change was applied. Do not paste credentials or signed URLs.',flush=True)
        sys.exit(1)
