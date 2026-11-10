"""Product facts for conversational answers; never execution authority.

Keep tool names tied to the existing registry. Runtime permissions, connectivity,
feature gates and evidence are checked separately by domain services.
"""
SUPPORTED_TOOL_NAMES = (
    'list_companies', 'company_masters', 'read_stock', 'read_report',
    'read_purchase_draft', 'create_purchase_draft', 'purchase_context',
    'check_purchase_tax', 'purchase_preview', 'receipt_preview',
    'read_bill_fields', 'document_status', 'list_documents', 'extract_document',
    'link_receipt', 'evaluate_automation',
)


def conversation_capabilities():
    return {
        'assistant_name': 'Philixa',
        'available_tool_types': list(SUPPORTED_TOOL_NAMES),
        'can_explain_and_chat': True,
        'agent_scope': 'A bounded task-driven agent can select permitted accounting tools and track tasks. It is not an unrestricted autonomous accountant; writes require approval/policy and verified results.',
        'limitations': [
            'No internet search/browsing tool is connected to this assistant.',
            'No direct banking payment, tax-return filing or travel-booking tool.',
            'Sales/payment/bank transaction automation is not a released capability.',
            'Supported reads require permitted company and available connector/data.',
            'Draft creation is not posting; writes need existing approval/policy and native verification.',
            'Document extraction can fail and requires review; do not guarantee accuracy.',
        ],
        'not_authority': 'This catalogue describes tools, not current permissions, connection status or successful execution.',
    }
