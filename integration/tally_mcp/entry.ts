// ISC upstream builders are imported; its server/audit/approval map are deliberately unused.
import { Server } from '@modelcontextprotocol/sdk/server/index.js';
import { StdioServerTransport } from '@modelcontextprotocol/sdk/server/stdio.js';
import { ListToolsRequestSchema, CallToolRequestSchema } from '@modelcontextprotocol/sdk/types.js';
import { tools, handleTool, buildWriteXml } from './tools.js';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';

const registry = JSON.parse(readFileSync(fileURLToPath(new URL('../registry.json', import.meta.url)), 'utf8'));
const contracts = new Map<string, any>(registry.tools.map((t: any) => [t.name, t]));
const server = new Server({ name: 'philixa-tally-adapter', version: '0.1.0' }, { capabilities: { tools: {} } });
server.setRequestHandler(ListToolsRequestSchema, async () => ({ tools: tools.map(t => ({
  ...t, inputSchema: contracts.get(t.name).inputSchema
})) }));
server.setRequestHandler(CallToolRequestSchema, async ({ params }) => {
  // Python validates strict schemas before dispatch. Child also rejects unknown/write calls.
  const name = params.name;
  const args = params.arguments ?? {};
  try {
    if (name === 'philixa_compile') {
      const tool = String(args.tool ?? '');
      const contract = contracts.get(tool);
      if (!contract || contract.category !== 'write' || !contract.builderAvailable) throw new Error('compiler_unavailable');
      const xml = await buildWriteXml(tool, args.arguments as Record<string, unknown>);
      return { content: [{ type: 'text' as const, text: JSON.stringify({ xml }) }] };
    }
    const contract = contracts.get(name);
    if (!contract || contract.state !== 'read_candidate' || contract.category !== 'read') throw new Error('capability_blocked');
    let result = await handleTool(name, args);
    if (name === 'get_health_check') {
      const health = JSON.parse(result);
      result = JSON.stringify({ gatewayReachable: health.gatewayReachable, companyOpen: health.companyOpen,
        errorCode: health.connectionError ? 'gateway_read_failed' : null });
    }
    return { content: [{ type: 'text' as const, text: result }] };
  } catch {
    // No raw accounting fields, narration, upstream errors, or URLs in diagnostics.
    return { isError: true, content: [{ type: 'text' as const, text: 'mcp_operation_failed' }] };
  }
});
await server.connect(new StdioServerTransport());
