"""Accountant-facing reports; no generated totals, SQL, retrieval or answer model."""
import json
import re
from datetime import date
from decimal import Decimal, InvalidOperation
from app.services.tally_mcp import CONTRACTS
from app.services.tally_connector import TallyError

LABELS = {
    'get_ledgers':'Ledger list', 'get_stock_items':'Stock item masters',
    'get_vouchers':'Day book', 'get_company_info':'Company details',
    'get_profit_and_loss':'Profit and loss', 'get_balance_sheet':'Balance sheet',
    'get_trial_balance':'Trial balance', 'get_groups':'Account groups',
    'get_voucher_types':'Voucher types', 'get_cost_centres':'Cost centres',
    'get_stock_summary':'Stock summary', 'get_bills_receivable':'Receivables',
    'get_bills_payable':'Payables', 'get_cash_flow':'Cash flow',
    'get_funds_flow':'Funds flow', 'get_ratio_analysis':'Ratio analysis',
    'get_sales_register':'Sales register', 'get_purchase_register':'Purchase register',
    'get_journal_register':'Journal register', 'get_payment_register':'Payment register',
    'get_receipts_and_payments':'Receipts and payments', 'get_reorder_status':'Reorder status',
    'get_vat_liability_summary':'VAT liability', 'get_gst_liability_summary':'GST liability',
    'get_ledger_vouchers':'Ledger transactions', 'get_health_check':'Connection check',
}

def report_catalog():
    return [{'tool':key,'label':LABELS[key], 'schema':c['inputSchema']}
            for key,c in CONTRACTS.items() if c['category']=='read']

def dates(arguments):
    """Only normalize explicitly supplied dates. Never select a reporting period silently."""
    result=dict(arguments)
    for key in ('from','to','asOf'):
        if key not in result:continue
        v=result[key]
        if not isinstance(v,str):raise TallyError('Invalid report date.')
        try:
            if re.fullmatch(r'\d{4}-\d{2}-\d{2}',v):d=date.fromisoformat(v)
            elif re.fullmatch(r'\d{2}-\d{2}-\d{4}',v):
                day,month,year=map(int,v.split('-'));d=date(year,month,day)
            else:raise ValueError()
        except ValueError:raise TallyError('Report date invalid; YYYY-MM-DD date dein.') from None
        result[key]=d.strftime('%d-%m-%Y')
    if 'from' in result and 'to' in result:
        def ordered(v):return tuple(reversed(tuple(map(int,v.split('-')))))
        if ordered(result['from'])>ordered(result['to']):raise TallyError('Report start date must be before end date.')
    return result

def text(value):
    return '' if value is None else str(value)

def purchase_summary(envelope):
    """Present the native monthly register, without inventing voucher details or totals."""
    periods=envelope['DSPPERIOD']; info=envelope['DSPACCINFO']
    periods=periods if isinstance(periods,list) else [periods]
    info=info if isinstance(info,list) else [info]
    if len(periods)!=len(info):raise TallyError('Purchase report columns do not match; review required.')
    def amount(value, magnitude=False):
        if value is None or value=='':return ''
        if not isinstance(value,str) or len(value)>100 or not re.fullmatch(r'-?\d+(?:\.\d+)?',value):
            raise TallyError('Purchase report amount invalid; review required.')
        try:number=Decimal(value)
        except InvalidOperation:raise TallyError('Purchase report amount invalid.') from None
        if magnitude:number=number.copy_abs()
        precision=max(2,-number.as_tuple().exponent)
        return '₹'+format(number,f',.{precision}f')
    rows=[]
    for period,entry in zip(periods[:2000],info[:2000]):
        if not isinstance(period,str) or not isinstance(entry,dict):raise TallyError('Purchase report shape invalid.')
        values=[]
        for group,key in (('DSPDRAMT','DSPDRAMTA'),('DSPCRAMT','DSPCRAMTA'),('DSPCLAMT','DSPCLAMTA')):
            nested=entry.get(group)
            if not isinstance(nested,dict) or key not in nested:raise TallyError('Purchase report amount column missing.')
            values.append(nested[key])
        rows.append([period,amount(values[0],True),amount(values[1],True),amount(values[2])])
    return {'title':'Purchase register — monthly summary',
            'columns':['Month','Debit amount','Credit amount','Net amount (Tally signed)'],
            'rows':rows,'total_rows':len(periods),'truncated':len(periods)>2000,
            'note':'Monthly summary for the selected date range; rows are months, not individual vouchers. Debit/credit amounts show magnitudes. Net amount retains Tally’s sign (negative = debit). Blank amounts were not supplied by Tally.'}

def display(result, tool):
    """Lossless bounded source view. Parallel report arrays are paired only when lengths agree."""
    if not isinstance(result,dict) or result.get('isError'):raise TallyError('MCP report failed.')
    blocks=result.get('content')
    if not isinstance(blocks,list) or not blocks or any(b.get('type')!='text' for b in blocks):raise TallyError('Invalid report result.')
    if sum(len(b.get('text','')) for b in blocks)>1_500_000:raise TallyError('Report too large.')
    try:payload=json.loads('\n'.join(b['text'] for b in blocks),parse_float=str,parse_int=str)
    except (ValueError,KeyError,TypeError):raise TallyError('Report is not structured data.') from None
    def errors(v):
        if isinstance(v,dict):
            if any(k.upper() in ('LINEERROR','ERROR','ERRORMSG','TALLYREQUESTERROR') and val for k,val in v.items()):return True
            return any(errors(x) for x in v.values())
        return isinstance(v,list) and any(errors(x) for x in v)
    if errors(payload):raise TallyError('Tally rejected this report.')
    envelope=payload.get('ENVELOPE',payload) if isinstance(payload,dict) else {}
    if tool=='get_purchase_register' and isinstance(envelope,dict) and 'DSPPERIOD' in envelope:
        if 'DSPACCINFO' not in envelope:raise TallyError('Purchase report amount columns missing.')
        return purchase_summary(envelope)
    rows=None
    if isinstance(payload,list):rows=payload
    elif isinstance(payload,dict) and isinstance(payload.get('rows'),list):rows=payload['rows']
    elif isinstance(payload,dict) and isinstance(payload.get('DATA'),dict) and 'ROW' in payload['DATA']:
        value=payload['DATA']['ROW'];rows=value if isinstance(value,list) else [value] if value else []
    elif isinstance(envelope,dict) and 'BSNAME' in envelope and 'BSAMT' in envelope:
        names=envelope['BSNAME'];amounts=envelope['BSAMT']
        if not isinstance(names,list):names=[names]
        if not isinstance(amounts,list):amounts=[amounts]
        if len(names)!=len(amounts):raise TallyError('Balance sheet columns do not match; review required.')
        rows=[{'Account':n.get('DSPACCNAME',{}).get('DSPDISPNAME','') if isinstance(n,dict) else n,
               'Amount':a.get('BSMAINAMT',a.get('BSSUBAMT')) if isinstance(a,dict) else a} for n,a in zip(names,amounts)]
    elif isinstance(envelope,dict) and 'DSPACCNAME' in envelope and 'DSPACCINFO' in envelope:
        names=envelope['DSPACCNAME'];info=envelope['DSPACCINFO']
        if not isinstance(names,list):names=[names]
        if not isinstance(info,list):info=[info]
        if len(names)!=len(info):raise TallyError('Report columns do not match; review required.')
        rows=[{'Account':n,'Balance':a} for n,a in zip(names,info)]
    if rows is None:
        # Export formats differ by installed Tally version. Keep nested source fields;
        # do not invent matching rows or computed totals for an unknown format.
        rows=[payload] if payload else []
    flattened=[]
    def flatten(v,prefix='',depth=0):
        if depth>12:raise TallyError('Report nesting exceeds limit.')
        if isinstance(v,dict):
            output={}
            for k,x in v.items():output.update(flatten(x,f'{prefix} / {k}' if prefix else k,depth+1))
            return output
        if isinstance(v,list):return {prefix:json.dumps(v,ensure_ascii=False)}
        return {prefix or 'Value':text(v)}
    for row in rows[:2000]:flattened.append(flatten(row))
    columns=list(dict.fromkeys(k for row in flattened for k in row))
    if len(columns)>100:raise TallyError('Report shape too wide; use a narrower period.')
    return {'title':LABELS[tool], 'columns':columns,
            'rows':[[row.get(c,'') for c in columns] for row in flattened],
            'total_rows':len(rows), 'truncated':len(rows)>2000,
            'note':payload.get('note') if isinstance(payload,dict) else None}
