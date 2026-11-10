"""Display a new purchase using confirmed quantities and suggested old prices."""
from decimal import Decimal,InvalidOperation

def proposal(content,context):
    hint=context.get('supplier_suggestion') or {}
    supplier=hint.get('supplier') or content.get('party_name')
    rates=hint.get('rates') or context.get('suggestions') or []
    if context.get('status')!='ready' or not supplier or not rates:return None
    suggested={r['field']:r for r in rates}
    lines=[];subtotal=Decimal('0');complete=True
    try:
        for index,line in enumerate(content.get('lines',[])):
            evidence=suggested.get(f'{index}:rate')
            rate=line.get('rate') if line.get('rate') is not None else evidence.get('value') if evidence else None
            quantity=line.get('quantity')
            if rate is None or quantity is None:complete=False
            else:subtotal+=Decimal(str(quantity))*Decimal(str(rate))
            lines.append({'item':line.get('item_name'),'quantity':quantity,'unit':line.get('unit'),
                'rate':rate,'rate_status':'suggested' if evidence and line.get('rate') is None else 'explicit',
                'historical_date':evidence.get('entry_date') if evidence else None})
    except (InvalidOperation,TypeError):return None
    return {'supplier':supplier,'lines':lines,'subtotal_before_discount_tax':str(subtotal.quantize(Decimal('.01'))) if complete else None,
        'confirmation_scope':'supplier_and_suggested_rates_only','new_transaction':True,
        'note':'Nayi purchase ka suggestion. Purani invoice/date/tax copy nahi honge; abhi entry nahi hui.'}
