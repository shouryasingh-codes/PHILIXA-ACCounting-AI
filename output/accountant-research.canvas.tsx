import {Stack,H1,H2,Text,Table,Callout,useHostTheme} from 'cursor/canvas';
const cases=[['C01','Clean purchase PDF','590.00','Pass'],['C02','Mixed rates + discount PDF','1324.50','Pass'],['C03','Explicit rounding PDF','1180.00','Pass'],['C04','Interstate PDF','708.00','Pass'],['C05','Clean PNG','660.80','Pass after parser fix'],['C06','Tilted JPEG','708.00','Pass after parser fix'],['C07','Wrong printed total','999.00','Original retained; calculation rejected'],['C08','Wrong buyer','236.00','Company mismatch blocked'],['C09','Missing page','472.00','Incomplete source blocked'],['C10','Renamed C01 resend','590.00','Same hash + invoice identity detected']];
export default function AccountantResearch(){
 const t=useHostTheme();
 return <Stack gap={20} style={{padding:24,color:t.text.primary,background:t.bg.editor}}>
 <H1>Philixa — accountant workflow research</H1>
 <Text>24 October 2026 · Internet desk research and synthetic development tests. No accountant interview or observed handling-time study.</Text>
 <Callout tone="warning" title="Real-world accuracy remains unverified">First run: 8/10. After correcting wrapped table-header parsing: 10/10 unchanged source cases. Nine unique invoices; one exact resend. These cases are development evidence, not an untouched real-bill evaluation.</Callout>
 <H2>Accountant ka asal kaam</H2>
 <Text>Bill collect karo → sahi buyer/supplier aur complete pages check karo → quantity, price aur discount check karo → sahi Tally company/items/taxes mein record karo → saved entry, stock aur dues verify karo. Payment matching aur month-end reconciliation alag continuing work hai.</Text>
 <Text>Purchase order aur goods-receipt evidence business ke workflow par depend karte hain. Bill milna maal milne ka proof nahi. Ek bill ka GST calculation sahi hona tax-credit eligibility ya return filing complete hona nahi hai.</Text>
 <H2>Philixa ko kahan value deni chahiye</H2>
 <Text>Original bill se correct draft, doubtful fields ka focused review, duplicate/wrong-company protection aur actual saved result ki verification. Tally already supports bank-statement import and matching: uske existing tools ko baseline banana hoga. Accountant ke broader job ko purchase entry se replace hua nahi maan sakte.</Text>
 <H2>Frozen 10-case pack — expected behaviour</H2>
 <Table headers={['Case','Source / scenario','Printed total ₹','Observed outcome']} rows={cases}/>
 <Text>Six valid sources compiled using synthetic configured masters; no Tally dispatch. Four exception cases exercised calculation/source/identity guards. C10 tests hash and business identity equality; persisted duplicate rejection is covered separately by regression tests. Inputs and expected answers were frozen before extraction; hashes were checked after the run.</Text>
 <H2>Photo fix</H2>
 <Text>A wrapped GST percent sign was being treated as a serial-number header. A split No. header could also leak its row number into the item name. The parser now recognises these explicit spatial header fragments, preserves source crop coordinates and still rejects incomplete actual item rows. No master-based unit invention was added.</Text>
 <H2>Cost and practical limits</H2>
 <Text>Zero cloud API calls. No native voucher posted, no user accounting data changed. PDF/PNG/JPEG tests used free embedded text or local RapidOCR. Photos still require review. No measured time savings, universal OCR score, blur/handwriting claim or production automation approval.</Text>
 <H2>Primary references</H2>
 <Text><a href="https://villgro.org/wp-content/uploads/2024/07/Accounts-Executive-JD-2024.docx.pdf">Employer job description</a> · <a href="https://help.tallysolutions.com/purchase-process-in-tallyprime/">Tally purchase lifecycle</a> · <a href="https://help.tallysolutions.com/gst-purchases-tally/">GST purchase entry</a> · <a href="https://help.tallysolutions.com/purchase-order-tally/">Orders and receipts</a> · <a href="https://help.tallysolutions.com/receivables-payables-tracking-methods/">Invoice-level dues</a> · <a href="https://help.tallysolutions.com/bank-reconciliation-tally/">Existing bank matching</a> · <a href="https://tutorial.gst.gov.in/userguide/returns/FAQ_gstr2b.htm">GSTN reconciliation guidance</a></Text>
 <Text>Full research: ACCOUNTANT_RESEARCH_2026_10_24.md. Evidence: data/accountant-pack/report.json, archived first/final runs and frozen manifest. Reproduce: python -m scripts.evaluate_accountant_pack inside the app container.</Text>
 </Stack>;
}
