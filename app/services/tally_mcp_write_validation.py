"""Deterministic write checks shared by server and connector.

These checks do not certify a Tally operation or authorize an import. They keep
the pinned compiler's broad schemas from accepting empty accounting entries,
unbalanced journals, implicit dates or arbitrary XML master fields.
"""
from datetime import datetime, date
from decimal import Decimal, InvalidOperation, localcontext
from zoneinfo import ZoneInfo
from app.services.tally_connector import TallyError
from app.services.tally_mcp import validate_arguments


def amount(value):
    try:
        result = Decimal(str(value))
        if not result.is_finite(): raise InvalidOperation
        return result
    except (InvalidOperation, ValueError, TypeError):
        raise TallyError('Accounting number invalid.') from None


def validate_write(tool, args, *, today=None):
    contract = validate_arguments(tool, args, read_only=False)
    if contract['category'] != 'write' or not contract['builderAvailable']:
        raise TallyError('Operation is not a supported write builder.')
    today = today or datetime.now(ZoneInfo('Asia/Kolkata')).date()
    if tool == 'create_vouchers_batch':
        rows = args.get('vouchers', [])
        if not 1 <= len(rows) <= 50: raise TallyError('Batch must contain 1–50 vouchers.')
        keys = [(row['voucherType'], row['narration'].strip()) for row in rows]
        if any(not text for _, text in keys) or len(set(keys)) != len(keys):
            raise TallyError('Batch voucher references must be nonempty and unique.')
        for row in rows: validate_write('create_voucher', row, today=today)
        return contract

    def inspect(obj):
        if isinstance(obj, dict):
            if obj.get('extraFields'):
                raise TallyError('Arbitrary master/XML fields are not permitted.')
            for key, val in obj.items():
                if key in ('date', 'referenceDate', 'gstDetailsApplicableFrom', 'addressApplicableFrom') and val:
                    try:
                        # Upstream write builders accept DD-MM-YYYY. Never let
                        # JavaScript normalize a nonexistent date into another day.
                        parsed = datetime.strptime(val, '%d-%m-%Y').date()
                    except (ValueError, TypeError):
                        raise TallyError('Write date must be a valid DD-MM-YYYY date.') from None
                    if key == 'date' and parsed > today:
                        raise TallyError('Future voucher date is not supported.')
                if isinstance(val, str) and key not in ('narration', 'description') and not val.strip():
                    raise TallyError('Accounting fields cannot contain blank names.')
                inspect(val)
        elif isinstance(obj, list):
            for val in obj: inspect(val)
    inspect(args)
    if tool in ('create_voucher', 'update_voucher'):
        rows = args.get('entries')
        if rows is not None:
            if len(rows) < 2: raise TallyError('A voucher needs at least two ledger entries.')
            with localcontext() as ctx:
                ctx.prec = 50
                values = [amount(row.get('amount')) for row in rows]
                if any(v <= 0 or v != v.quantize(Decimal('.01')) for v in values):
                    raise TallyError('Ledger amounts need nonzero values with at most two decimals.')
                signed = [v * (-1 if row['type'] == 'debit' else 1) for v, row in zip(values, rows)]
                if sum(signed, Decimal(0)) != 0:
                    raise TallyError('Debit and credit amounts do not balance.')
        elif not (args.get('debitLedger') and args.get('creditLedger') and 'amount' in args):
            # Narration-only alter is a legitimate upstream edit. It still needs
            # a GUID/before-state review before any dispatch can be authorized.
            if tool != 'update_voucher' or not args.get('narration'):
                raise TallyError('Specify balanced ledger entries or debit/credit/amount.')
        else:
            value = amount(args['amount'])
            if value <= 0 or value != value.quantize(Decimal('.01')):
                raise TallyError('Voucher amount must be positive with at most two decimals.')
            if args['debitLedger'] == args['creditLedger']:
                raise TallyError('Debit and credit ledger must differ.')
    for field in ('items', 'sources', 'destinations', 'components', 'names'):
        if field in args and not args[field]: raise TallyError('Operation rows cannot be empty.')
    physical = tool.endswith('physical_stock')
    for row in args.get('items', []):
        quantity_key = 'actualQty' if physical else 'qty'
        if quantity_key in row:
            qty = amount(row[quantity_key])
            if qty < 0 or (not physical and qty == 0):
                raise TallyError('Count may be zero; transaction quantity must be positive.')
        if 'rate' in row and amount(row['rate']) < 0:
            raise TallyError('Inventory rate cannot be negative.')
        if 'discountPercent' in row and not 0 <= amount(row['discountPercent']) <= 100:
            raise TallyError('Discount must be between zero and 100 percent.')
    if physical:
        counted_date = datetime.strptime(args['date'], '%d-%m-%Y').date()
        if counted_date != today:
            raise TallyError('Physical count needs today’s IST date and live review; backdating is blocked.')
    return contract
