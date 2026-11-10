import {Stack,H1,H2,Text,useHostTheme} from 'cursor/canvas';
export default function AccountantPilot(){
 const t=useHostTheme();
 return <Stack gap={16} style={{padding:24,color:t.text.primary,background:t.bg.editor}}>
 <H1>Philixa: accountant-style pilot</H1>
 <Text>24 October 2026 · Philixa Test · Agent QA, not an accountant time study</Text>
 <H2>Reviewed purchase: native Tally verification passed</H2>
 <Text>Original PDF → extracted draft → reviewed preview → one approval → Purchase voucher 21. Reference PX/26-27/1023; date 02-Oct-2026; payable INR 2,417. Strict native payload verification passed.</Text>
 <ul><li>Item1:12 bags ×125;5% discount; taxable1,425; GST18%.</li><li>Item2:8 bags ×87.50;0% discount; taxable700; GST5%.</li><li>CGST145.75 + SGST145.75 + round-off0.50; taxable2,125.</li><li>Stock movements:122→134 bags and13→21 bags. Cement unchanged25.</li><li>Renamed reupload:0 new files,1 already saved; native invoice count remains1.</li><li>Purchase Register gross16,867.20 matches16 active native purchase vouchers. Report is a monthly summary, not invoice-level tracing.</li></ul>
 <H2>Daily accountant coverage remains incomplete</H2>
 <Text>Read-only runtime probes: receivables, payables, sales register and receipts/payments reports disabled. Bank reconciliation, GST/TDS filing and month-end work not passed by this pilot. Existing CRM tasks are not invoice-level dues matching.</Text>
 <Text>Native supplier bill allocation uses an internal GUID reference. Printed supplier-invoice tracing and outstanding matching require separate acceptance.</Text>
 <H2>What the research supports</H2>
 <Text>A sampled INR15,000–20,000/month junior-accountant job lists Tally entries, AP/AR, BRS and GST/TDS assistance. Employer-authored Villgro duties also include supporting vouchers, ledger reconciliation and month-end reporting. Work varies by employer and industry.</Text>
 <p><a href="https://in.indeed.com/viewjob?jk=c0d674ffea7ae676">Salary/role example</a> · <a href="https://villgro.org/wp-content/uploads/2024/07/Accounts-Executive-JD-2024.docx.pdf">Employer job description</a> · <a href="https://help.tallysolutions.com/gst-purchases-tally/">Tally purchase workflow</a> · <a href="https://help.tallysolutions.com/manage-receivables-outstanding-tally/">Tally dues workflow</a></p>
 <H2>No replacement or time-saving claim</H2>
 <Text>This invoice already guided a parser fix: it is development evidence, not held-out accuracy. No human manual baseline, real-bill study or50% savings measurement exists. No paid AI calls or real-company transactions were used.</Text>
 </Stack>;
}
