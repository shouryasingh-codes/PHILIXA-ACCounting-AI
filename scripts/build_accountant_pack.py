"""Original synthetic source pack. Expected values are literal, pre-extraction truth."""
import copy,hashlib,io,json,zipfile
from pathlib import Path
from reportlab.platypus import SimpleDocTemplate,Paragraph,Spacer,Table,TableStyle
from reportlab.lib.styles import getSampleStyleSheet,ParagraphStyle
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4,landscape
import pypdfium2
from PIL import Image

ROOT=Path('scripts/fixtures/accountant-v1')
OUTPUT=Path('output/pdf/accountant-v1')
LOCAL='Philixa GST TEST Supplier Local'
INTER='Philixa GST TEST Supplier Interstate'
ITEM18='Philixa GST TEST Goods18';ITEM5='Philixa GST TEST Goods5'
def line(item,q,rate,disc,gst,taxable):
 return dict(item_name=item,quantity=q,unit='bags',rate=rate,discount_percent=disc,gst_rate=gst,hsn='2523',taxable_amount=taxable)
def case(n,title,lines,taxes,total,fmt='pdf',layout='combined',rounding='0.00',inter=False,buyer='Philixa Test',outcome='review'):
 return dict(id=f'C{n:02}',title=title,format=fmt,layout=layout,expected_outcome=outcome,expected=dict(supplier_name=INTER if inter else LOCAL,buyer_name=buyer,invoice_number=f'QA26-{n:03}',invoice_date='2026-10-02',supplier_gstin='07ABCPF1234G1ZA' if inter else '06ABCPF1234G1ZC',place_of_supply='06',tax_treatment='regular_domestic_goods',invoice_discount='0.00',round_off=rounding,invoice_total=total,expected_taxes=taxes,lines=lines))
cases=[
 case(1,'Local purchase - one item',[line(ITEM18,'5','100.00','0','18','500.00')],{'CGST':'45.00','SGST':'45.00'},'590.00'),
 case(2,'Mixed rates and line discount',[line(ITEM18,'10','100.00','10','18','900.00'),line(ITEM5,'2','125.00','0','5','250.00')],{'CGST':'87.25','SGST':'87.25'},'1324.50',layout='separate'),
 case(3,'Paisa arithmetic and disclosed rounding',[line(ITEM18,'3','333.33','0','18','999.99')],{'CGST':'90.00','SGST':'90.00'},'1180.00',rounding='0.01'),
 case(4,'Interstate goods - IGST',[line(ITEM18,'3','200.00','0','18','600.00')],{'IGST':'108.00'},'708.00',inter=True,layout='separate'),
 case(5,'Clean PNG bill',[line(ITEM18,'7','80.00','0','18','560.00')],{'CGST':'50.40','SGST':'50.40'},'660.80',fmt='png'),
 case(6,'Mildly tilted compressed JPEG',[line(ITEM18,'6','100.00','0','18','600.00')],{'CGST':'54.00','SGST':'54.00'},'708.00',fmt='jpg'),
 case(7,'Wrong printed total - preserve and reject',[line(ITEM18,'5','100.00','0','18','500.00')],{'CGST':'45.00','SGST':'45.00'},'999.00',outcome='block_total'),
 case(8,'Bill belongs to another buyer',[line(ITEM18,'2','100.00','0','18','200.00')],{'CGST':'18.00','SGST':'18.00'},'236.00',buyer='Other Practice Buyer Pvt Ltd',outcome='block_company'),
 case(9,'Only first page supplied',[line(ITEM18,'4','100.00','0','18','400.00')],{'CGST':'36.00','SGST':'36.00'},'472.00',outcome='block_pages'),
]
duplicate=copy.deepcopy(cases[0]);duplicate.update(id='C10',title='Renamed resend of C01',expected_outcome='duplicate',duplicate_of='C01');cases.append(duplicate)

styles=getSampleStyleSheet();styles.add(ParagraphStyle(name='Bill',fontSize=9,leading=13));styles.add(ParagraphStyle(name='Cell',fontSize=8,leading=11))
def p(text,small=False):return Paragraph(str(text),styles['Cell' if small else 'Bill'])
def table(rows,widths):
 t=Table(rows,colWidths=widths,hAlign='LEFT');t.setStyle(TableStyle([('GRID',(0,0),(-1,-1),.5,colors.HexColor('#777777')),('VALIGN',(0,0),(-1,-1),'TOP'),('TOPPADDING',(0,0),(-1,-1),7),('BOTTOMPADDING',(0,0),(-1,-1),7)]));return t
def pdf_bytes(c):
 stream=io.BytesIO()
 b=c['expected'];wide=c['layout']=='separate';page=landscape(A4) if wide else A4;w=page[0]-72
 story=[p('<b>SYNTHETIC PRACTICE INVOICE - NOT VALID FOR PAYMENT OR TAX</b>',True),Spacer(1,8),Paragraph('TAX INVOICE',styles['Title'])]
 story.append(table([[p('<b>'+b['supplier_name']+'</b><br/>Unit 12, Practice Industrial Estate<br/>Dummy address, India<br/>GSTIN: '+b['supplier_gstin']),p('<b>Invoice No: '+b['invoice_number']+'</b><br/>Invoice Date: 02-Oct-2026<br/>Payment Terms: 15 days<br/>Reverse Charge: No')]], [w*.56,w*.44]))
 story.append(table([[p('<b>Bill To / Buyer</b><br/><b>'+b['buyer_name']+'</b><br/>Unit 4, Practice Business Park<br/>Dummy Haryana address<br/>GSTIN: 06ABCPE1234F1ZF'),p('<b>Ship To / Consignee</b><br/>'+b['buyer_name']+'<br/>Place of Supply: Haryana (06)<br/>Delivery: Practice only')]], [w*.56,w*.44]));story.append(Spacer(1,12))
 if wide:
  heads=['No.','Description of Goods','HSN','Unit','Qty','Rate INR','Disc %','Taxable Amount','GST %'];weights=[.04,.29,.07,.07,.06,.10,.07,.12,.08]
  cells=[[str(i+1),l['item_name'],l['hsn'],l['unit'],l['quantity'],l['rate'],l['discount_percent'],l['taxable_amount'],l['gst_rate']] for i,l in enumerate(b['lines'])]
 else:
  heads=['No.','Description of Goods','HSN','Qty / Unit','Rate Rs.','Disc. %','Taxable Rs.','GST %'];weights=[.04,.28,.07,.12,.12,.08,.12,.07]
  cells=[[str(i+1),l['item_name'],l['hsn'],l['quantity']+' '+l['unit'],l['rate'],l['discount_percent'],l['taxable_amount'],l['gst_rate']] for i,l in enumerate(b['lines'])]
 t=table([[p(v,True) for v in row] for row in [heads]+cells],[w*x for x in weights]);t.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,0),colors.HexColor('#eeeeee'))]));story.append(t);story.append(Spacer(1,12))
 # Separate, explicit header/value lines preserve the source labels without
 # pretending an accountant's document always has a particular visual layout.
 summary=[]
 for head,amount in b['expected_taxes'].items():summary.append([p(head),p(amount)])
 summary.extend([[p('Invoice Discount'),p(b['invoice_discount'])],[p('Round Off'),p(b['round_off'])],[p('<b>Grand Total</b>'),p('<b>'+b['invoice_total']+'</b>')]])
 story.append(table(summary,[w*.65,w*.35]));story.append(Spacer(1,14));story.append(p('Terms: practice data only. Item tax rates/HSN follow dummy test masters, not current commodity tax advice.',True));story.append(Spacer(1,12));story.append(p('<b>For '+b['supplier_name']+'</b><br/>Authorised Signatory: TEST COPY - UNSIGNED',True))
 def footer(canvas,doc):
  canvas.setFont('Helvetica',8);canvas.drawString(36,20,'Page 1 of '+('2' if c['id']=='C09' else '1'))
 SimpleDocTemplate(stream,pagesize=page,leftMargin=36,rightMargin=36,topMargin=28,bottomMargin=38).build(story,onFirstPage=footer,onLaterPages=footer)
 return stream.getvalue()

def main():
 if (ROOT/'hashes.json').exists():raise SystemExit('Frozen pack exists. Do not overwrite inputs; evaluate unchanged bytes.')
 ROOT.mkdir(parents=True,exist_ok=True);OUTPUT.mkdir(parents=True,exist_ok=True)
 manifest=dict(version='accountant-v1',scope='synthetic development QA; nine unique invoices, ten scenarios',research='ACCOUNTANT_RESEARCH_2026_10_24.md',no_native_posting=True,no_cloud_calls=True,cases=cases)
 # Truth is written before any extraction or compiler call.
 (ROOT/'manifest.json').write_text(json.dumps(manifest,indent=2))
 hashes={};thumbs=[];first=None
 for c in cases:
  if c['id']=='C10':data=first
  else:
   data=pdf_bytes(c)
  if c['format']!='pdf':
   doc=pypdfium2.PdfDocument(data);image=doc[0].render(scale=2.5).to_pil().convert('RGB');doc.close()
   if c['format']=='jpg':image=image.rotate(1.2,resample=Image.Resampling.BICUBIC,expand=True,fillcolor='white')
   buf=io.BytesIO();image.save(buf,format='PNG' if c['format']=='png' else 'JPEG',quality=88);data=buf.getvalue()
  else:
   doc=pypdfium2.PdfDocument(data);assert len(doc)==1;image=doc[0].render(scale=1).to_pil().convert('RGB');doc.close()
  if c['id']=='C01':first=data
  filename=c['id']+('-resend' if c['id']=='C10' else '')+'.'+c['format'];c['filename']=filename
  (ROOT/filename).write_bytes(data);(OUTPUT/filename).write_bytes(data);hashes[filename]=hashlib.sha256(data).hexdigest()
  image.thumbnail((330,470));thumbs.append((c['id'],image.copy()))
 manifest['cases']=cases;(ROOT/'manifest.json').write_text(json.dumps(manifest,indent=2));hashes['manifest.json']=hashlib.sha256((ROOT/'manifest.json').read_bytes()).hexdigest();(ROOT/'hashes.json').write_text(json.dumps(hashes,indent=2))
 from PIL import ImageDraw
 contact=Image.new('RGB',(5*350,2*510),'white');draw=ImageDraw.Draw(contact)
 for i,(label,img) in enumerate(thumbs):x=(i%5)*350;y=(i//5)*510;draw.text((x+10,y+5),label,fill='black');contact.paste(img,(x+10,y+28))
 contact.save(OUTPUT/'contact-sheet.png')
 with zipfile.ZipFile(OUTPUT/'accountant-10-scenarios.zip','w',zipfile.ZIP_DEFLATED) as z:
  for c in cases:z.write(OUTPUT/c['filename'],c['filename'])
  z.write(ROOT/'manifest.json','expected-answers.json')
 print('Frozen 10 scenarios,9 unique invoices; manifest and byte hashes saved before extraction.')
if __name__=='__main__':main()
