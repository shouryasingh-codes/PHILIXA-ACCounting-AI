"""Build the offline evaluation canvas; data is embedded, never fetched."""
import json
from pathlib import Path
report=json.loads(Path('data/day9/report.json').read_text())
data=json.dumps(report,ensure_ascii=False).replace('<','\\u003c')
source='''import {Stack,Row,Grid,H1,H2,Text,Table,Callout,Button,useHostTheme,useCanvasState} from 'cursor/canvas';
const report = REPORT_DATA;
export default function PhilixaEvaluation(){
 const t=useHostTheme();const [detail,setDetail]=useCanvasState('show-field-differences',false);
 const stages=Object.entries(report.summary).map(([name,value])=>[name,`${value.passed}/${value.total}`,name==='extraction'?'Whole source files exact':name==='posting'?'In-memory simulated Tally; golden inputs':name==='accounting'?'Valid and rejection cases; golden inputs':'Identity acceptance/rejection']);
 const fields=report.field_accuracy;
 return <Stack gap={20} style={{padding:24,color:t.text.primary,background:t.bg.editor,fontSize:14}}>
  <H1>Philixa / Day 9 evaluation</H1>
  <Callout tone="warning" title="Real-world accuracy unverified">Synthetic evaluation complete. No accountant study, human time savings or production accuracy claim. {report.quality_gate_passed?'All bounded synthetic quality gates passed.':'The extraction quality gate did not pass.'}</Callout>
  <Row gap={24} wrap><div><H2>{fields.correct}/{fields.total} fields</H2><Text>Strict synthetic extraction evidence</Text></div><div><H2>{report.summary.extraction.passed}/{report.summary.extraction.total} exact files</H2><Text>Failures retained in denominator</Text></div><div><H2>External API: $0</H2><Text>Offline/local run; compute cost excluded</Text></div></Row>
  <H2>Stages measured separately</H2><Table headers={['Stage','Correct / total','Meaning']} rows={stages}/>
  <Text>Source: scripts/fixtures/day9/golden.json / {report.run_at}. Field normalization permits numeric formatting and parsed dates; missing explicit zero evidence still counts as missing. These scores are not an end-to-end accuracy rate.</Text>
  <H2>Per synthetic file</H2><Table headers={['File','Fields correct','Golden discrepancies','Processing ms','Human review']} rows={report.extraction.map(r=>[r.id,`${r.correct}/${r.total}`,r.correction_count,r.latency_ms,'Unmeasured'])}/>
  <Text>PDF latency = parser execution. PNG/JPEG latency includes isolated local OCR process startup. Single observations, not a throughput benchmark. Golden discrepancies are not observed or necessarily required human edits.</Text>
  {report.extraction.some(r=>r.differences.length>0)&&<Button onClick={()=>setDetail(!detail)}>{detail?'Hide':'Show'} exact field differences</Button>}
  {detail&&report.extraction.some(r=>r.differences.length>0)&&<Table headers={['File','Field','Expected','Observed']} rows={report.extraction.flatMap(r=>r.differences.map(d=>[r.id,d.field,String(d.expected),String(d.actual)]))}/>}
  <H2>What the results mean</H2><Text>{report.quality_gate_passed?'All bounded synthetic stages passed. Earlier supplier-header, explicit invoice-discount and unit-reading discrepancies were addressed. Crop consensus retains the initial OCR evidence and photo review gates.':'Some bounded synthetic stages still fail; inspect the field differences.'} Keep accountant review active. A small synthetic corpus does not establish real-world accuracy.</Text>
  <Grid columns={2} gap={24}><div><H2>Measurement now available</H2><Text>Per-bill persisted correction counts, deduplicated active-review samples, extraction attempt latency/cost availability and posting queue-to-result timing. Client review timing excludes hidden/unfocused, busy and idle periods; it is an estimate and may miss closed-tab intervals.</Text></div><div><H2>Accountant comparison protocol</H2><Text>Use authorised anonymised bills and the same accountant in balanced workflow order. Include upload, review with corrections and exception time. Keep overlapping processing wall time separate. No comparison or savings is reported until those observations exist.</Text></div></Grid>
  <H2>Reproduce</H2><code style={{color:t.text.secondary}}>docker compose exec -T app python -m scripts.evaluate_day9</code>
  <Text>Full results: data/day9/report.json and report.md. Source hashes and generated input hashes are retained. Posting uses an isolated SQLite journal and simulated transport; no real Tally entry was posted for Day 9.</Text>
 </Stack>;
}
'''.replace('REPORT_DATA',data)
Path('data/day9/philixa-day9-evaluation.canvas.tsx').write_text(source,encoding='utf-8')
print('Built offline Day 9 evaluation canvas')
