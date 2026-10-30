const PROJECT_READ_TOOL = {
  type: "function",
  name: "arco_project_read",
  description: "Read methods and datasets through the ArcRho Gateway. Call with kind=catalog first to discover read kinds and their arguments. project_name defaults to the project open in the UI; pass it only when the user asks about another project (kind=project_names lists them all). reserving_class defaults to the class open in the UI when omitted. No saves or mutations are available.",
  inputSchema: {
    type: "object", properties: {
      kind: { type: "string" },
      arguments: { type: "object", additionalProperties: true },
    }, required: ["kind", "arguments"], additionalProperties: false,
  },
};

// The agent read list in arcrho_mcp.reads is shared with the Arco MCP server:
// method loads, dataset loads and the discovery reads, never simulations or
// mutations. Any project on the server may be read; the open one is the default.
const PROJECT_READ_SCRIPT = `
import json, sys
from arcrho_mcp.reads import agent_read_catalog, agent_read_spec
from arcrho_api.gateway import GatewayClient
request = json.load(sys.stdin)
project = request['project']
kind = request['kind']
if kind == 'catalog':
    result = agent_read_catalog()
else:
    spec = agent_read_spec(kind)
    arguments = request.get('arguments') or {}
    names_project = 'project_name' in (*spec.required, *spec.optional)
    if names_project and not arguments.get('project_name'):
        if not project:
            raise ValueError('No project is open; pass project_name')
        arguments['project_name'] = project
    # The open class belongs to the open project; another project gets no default.
    active_class = request.get('reserving_class') or ''
    if (active_class and arguments.get('project_name') == project
            and not arguments.get('reserving_class') and 'reserving_class' in (*spec.required, *spec.optional)):
        arguments['reserving_class'] = active_class
    result = GatewayClient().read(kind, **arguments)
print(json.dumps(result, ensure_ascii=False))
`;

function activeProject(context) {
  if (context?.disabled) return "";
  return String(context?.fields?.project || context?.projectInstance?.projectName || context?.projectName || "").trim();
}

// The reserving class open in the UI; reads default to it when ArcBot names none.
function activeReservingClass(context) {
  if (context?.disabled) return "";
  return String(context?.activeNestedWindow?.path || context?.projectInstance?.selectedPath || context?.fields?.reservingClass || "").trim();
}

async function readArcBotProject(params, context, runPython) {
  const project = activeProject(context);
  const input = params?.arguments || {};
  if (params?.tool !== PROJECT_READ_TOOL.name) throw new Error("Unsupported ArcBot tool.");
  return runPython(PROJECT_READ_SCRIPT, JSON.stringify({ project, reserving_class: activeReservingClass(context), kind: input.kind, arguments: input.arguments || {} }));
}

module.exports = { PROJECT_READ_TOOL, PROJECT_READ_SCRIPT, activeProject, activeReservingClass, readArcBotProject };
