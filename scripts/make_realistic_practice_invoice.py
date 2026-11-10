"""Create an original realistic-layout practice invoice; no upload or posting."""
from pathlib import Path
from decimal import Decimal as D
from reportlab.platypus import SimpleDocTemplate,Paragraph,Spacer,Table,TableStyle
from reportlab.lib.styles import getSampleStyleSheet,ParagraphStyle
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from pypdf import PdfReader

out=Path('output/pdf');out.mkdir(parents=True,exist_ok=True)
target=out/'Philixa-Practice-Purchase-PX-26-27-1023.pdf'
styles=getSampleStyleSheet()
styles.add(ParagraphStyle(name='SmallBill',fontName='Helvetica',fontSize=9,leading=13))
styles.add(ParagraphStyle(name='TinyBill',fontName='Helvetica',fontSize=8,leading=11))
def p(s,small=False):return Paragraph(s,styles['TinyBill' if small else 'SmallBill'])
def grid(rows,widths):
 t=Table(rows,colWidths=widths,hAlign='LEFT')
 t.setStyle(TableStyle([('GRID',(0,0),(-1,-1),.5,colors.HexColor('#777777')),('VALIGN',(0,0),(-1,-1),'TOP'),('LEFTPADDING',(0,0),(-1,-1),7),('RIGHTPADDING',(0,0),(-1,-1),7),('TOPPADDING',(0,0),(-1,-1),7),('BOTTOMPADDING',(0,0),(-1,-1),7)]))
 return t
story=[p('<b>TEST COPY - SYNTHETIC DATA - NOT VALID FOR TAX OR PAYMENT</b>',True),Spacer(1,12),Paragraph('TAX INVOICE',styles['Title'])]
story.append(grid([[p('<b>Philixa GST TEST Supplier Local</b><br/>Unit 12, Practice Industrial Estate<br/>Faridabad, Haryana - 121001<br/><b>GSTIN:</b> 06ABCPF1234G1ZC<br/>State: Haryana | Code: 06'),p('<b>Invoice No:</b> PX/26-27/1023<br/><b>Invoice Date:</b> 02-Oct-2026<br/>Delivery Note: TEST-DN-1023<br/>Payment Terms: 15 days<br/>Reverse Charge: No')]], [285,226]))
story.append(grid([[p('<b>Bill To / Buyer</b><br/><b>Philixa Test</b><br/>Unit 4, Practice Business Park<br/>Faridabad, Haryana - 121001<br/><b>GSTIN:</b> 06ABCPE1234F1ZF'),p('<b>Ship To / Consignee</b><br/>Philixa Test<br/>Same as billing address<br/><b>Place of Supply:</b> Haryana (06)<br/>Dispatch: Local delivery (test)')]], [285,226]))
story.append(Spacer(1,14))
header=['No.','Description of Goods','HSN','Qty / Unit','Rate Rs.','Disc. %','Taxable Rs.','GST %']
rows=[[p(x,True) for x in header]]
for row in [['1','Philixa GST TEST Goods18','2523','12 bags','125.00','5','1,425.00','18'],['2','Philixa GST TEST Goods5','2523','8 bags','87.50','0','700.00','5']]:rows.append([p(x,True) for x in row])
t=grid(rows,[25,155,38,53,55,42,76,67]);t.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,0),colors.HexColor('#eeeeee'))]));story.append(t)
story.append(Spacer(1,13))
tax=[['Taxable value','CGST rate','CGST Rs.','SGST rate','SGST Rs.','Total tax Rs.'],['1,425.00','9%','128.25','9%','128.25','256.50'],['700.00','2.5%','17.50','2.5%','17.50','35.00'],['2,125.00','','145.75','','145.75','291.50']]
story.append(p('<b>GST tax summary (intra-state)</b>'))
story.append(grid([[p(x,True) for x in row] for row in tax],[95,77,85,77,85,92]))
story.append(Spacer(1,13))
summary=[['Gross amount','2,200.00'],['Line discount','75.00'],['Invoice discount','0.00'],['Taxable amount','2,125.00'],['CGST','145.75'],['SGST','145.75'],['Round Off','+0.50'],['Grand Total','2,417.00']]
totals=grid([[p('<b>'+a+'</b>' if a=='Grand Total' else a),p('<b>'+b+'</b>' if a=='Grand Total' else b)] for a,b in summary],[155,100])
story.append(Table([[p('<b>Amount in words</b><br/>Indian Rupees Two Thousand Four Hundred Seventeen Only.<br/><br/><b>Terms</b><br/>1. Quantities and prices are dummy values.<br/>2. All addresses and identifiers are synthetic practice data.<br/>3. Date is deliberately 02-Oct-2026 for the existing Tally EDU test setup.'),totals]],colWidths=[256,255],style=[('VALIGN',(0,0),(-1,-1),'TOP'),('LEFTPADDING',(0,0),(-1,-1),0),('RIGHTPADDING',(0,0),(-1,-1),0)]))
story.append(Spacer(1,15));story.append(p('<b>For Philixa GST TEST Supplier Local</b><br/>Authorised Signatory: TEST COPY - UNSIGNED',True))
def footer(c,doc):
 c.setFont('Helvetica',7);c.drawString(42,24,'Original synthetic practice specimen | Master names/tax rates follow existing test setup, not current commodity advice.');c.drawRightString(553,14,'Page 1 of 1')
SimpleDocTemplate(str(target),pagesize=A4,rightMargin=42,leftMargin=42,topMargin=32,bottomMargin=40).build(story,onFirstPage=footer,onLaterPages=footer)
assert D('1425')+D('700')+D('145.75')*2+D('.50')==D('2417')
reader=PdfReader(target);assert len(reader.pages)==1
text=reader.pages[0].extract_text()
for expected in ('PX/26-27/1023','Philixa Test','2,417.00','145.75','12 bags','8 bags'):assert expected in text,expected
print(target.resolve())
