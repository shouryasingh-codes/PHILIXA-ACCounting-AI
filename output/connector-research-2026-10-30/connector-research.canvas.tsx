import {Stack,Row,H1,H2,Text,Button,Callout,Link,useCanvasState,useHostTheme} from 'cursor/canvas';

const sources=[
 ['Exact Windows policy ID','https://learn.microsoft.com/en-us/windows/security/application-security/application-control/app-control-for-business/operations/inbox-appcontrol-policies'],
 ['SAC: no ordinary per-app Allow option','https://support.microsoft.com/en-us/windows/security/threat-malware-protection/smart-app-control-frequently-asked-questions'],
 ['Signing for Smart App Control','https://learn.microsoft.com/en-us/windows/apps/develop/smart-app-control/code-signing-for-smart-app-control'],
 ['SmartScreen reputation and EV limitations','https://learn.microsoft.com/en-us/windows/apps/package-and-deploy/smartscreen-reputation'],
 ['Store/MSIX signing','https://learn.microsoft.com/en-us/windows/msix/package/sign-msix-package-guide'],
 ['Current Store account requirements','https://learn.microsoft.com/en-us/windows/apps/publish/partner-center/open-a-developer-account'],
 ['Azure Public Trust geography','https://learn.microsoft.com/en-us/azure/artifact-signing/quickstart'],
 ['MSIX compatibility checklist','https://learn.microsoft.com/en-us/windows/msix/desktop/desktop-to-uwp-prepare'],
 ['HTTPX validating TLS context','https://www.python-httpx.org/advanced/ssl/'],
 ['PyInstaller runtime paths','https://pyinstaller.org/en/stable/runtime-information.html'],
 ['PyInstaller SAC issue 6747','https://github.com/pyinstaller/pyinstaller/issues/6747'],
 ['Reddit: unsigned Python executables','https://www.reddit.com/r/Python/comments/1ufer3u/windows_defender_blocks_python_executables/'],
 ['Reddit: solo-developer signing experience','https://www.reddit.com/r/dotnet/comments/1vpzzf9/solo_devs_shipping_windows_apps_is_code_signing/'],
 ['SignPath eligibility','https://signpath.org/terms']
];

export default function ConnectorResearch(){
 const t=useHostTheme();
 const [view,setView]=useCanvasState('philixa-connector-research-2026-10-30','Seedhi baat');
 return <Stack gap={16} style={{padding:24,color:t.text.primary,background:t.bg.editor,fontSize:14}}>
  <Text>PHILIXA / RESEARCH CHECKED 30 OCTOBER 2026 / INDIA</Text>
  <H1>Connector: do alag problems</H1>
  <Callout tone="info" title="Windows block confirmed; runtime file cause still unproved">
   Exact logged policy ID matches Smart App Control. The packaged network client also failed with FileNotFoundError. Signing alone cannot repair a runtime resource problem.
  </Callout>
  <Row gap={8} wrap>{['Seedhi baat','Evidence','Solutions','Next steps','Sources'].map(v=><Button key={v} onClick={()=>setView(v)}>{v}</Button>)}</Row>
  {view==='Seedhi baat'&&<>
   <H2>1. Windows publisher ko trust nahi kar raha</H2>
   <Text>Installer unsigned hai. Smart App Control enforcement PC par active mila. Yeh sirf browser download warning nahi; company laptop hona bhi prove nahi hota.</Text>
   <H2>2. Connector ka network client file nahi dhoondh pa raha</H2>
   <Text>FileNotFoundError confirmed hai, lekin exact missing file abhi unknown hai. CA-path fix plausible hai; source tests packaged acceptance ka replacement nahi.</Text>
   <H2>Budget ke liye pehla assessment</H2>
   <Text>Store-distributed MSIX feasibility check karo: Store signing mil sakti hai. Current helper ke startup, credentials, SQLite journal aur updates adapt/test karne honge. Same unsigned EXE upload karna solution nahi.</Text>
   <Text>Research did not enable the feature, modify security settings, purchase a certificate or publish an installer.</Text>
  </>}
  {view==='Evidence'&&<>
   <H2>Confirmed on this PC</H2>
   <Text>Code Integrity events 3077/3033; policy 0283ac0f-fff1-49ae-ada1-8a933130cad6; unsigned installer. Registry VerifiedAndReputablePolicyState = 1.</Text>
   <Text>CiTool policy inventory was denied access. We did not treat that failed command as a successful full inventory.</Text>
   <H2>Correction to earlier explanation</H2>
   <Text>“Enterprise signing” event wording is not proof of enterprise management. Microsoft identifies this GUID as VerifiedAndReputableDesktop, used by Smart App Control.</Text>
   <H2>What remains uncertain</H2>
   <Text>The build manifest already lists certifi/cacert.pem. A bad runtime path is plausible, but “certificate file omitted” is not established. Need a sanitized packaged traceback and actual resolved path.</Text>
   <Text>GitHub and Reddit provide related failures, not proof that our new binary works. No Windows barrier was bypassed.</Text>
  </>}
  {view==='Solutions'&&<>
   <H2>Store-distributed MSIX</H2>
   <Text>Store signing and currently free registration are useful. Trade-offs: identity/account eligibility, certification, packaging changes and lifecycle testing. An EXE/MSI Store listing still needs publisher signing.</Text>
   <H2>Direct signed EXE</H2>
   <Text>Use an eligible publicly trusted provider and verify the installed dependency set. Trade-offs: validation/cost and reputation warnings can remain. EV is not an instant SmartScreen guarantee.</Text>
   <H2>Azure Artifact Signing</H2>
   <Text>Current Public Trust individual eligibility is US/Canada. India is not in the listed public organization geographies either. Private Trust or Azure credits do not automatically solve customer-PC trust.</Text>
   <H2>Open-source assistance</H2>
   <Text>SignPath Foundation has real OSS licensing and project conditions. Proprietary Philixa eligibility is not established. This is not a reason to misrepresent licensing.</Text>
  </>}
  {view==='Next steps'&&<>
   <H2>First choose a supported distribution route</H2>
   <Text>Assess MSIX compatibility before buying signing services. Check the right Store account type for a commercial product.</Text>
   <H2>Then prove packaged networking</H2>
   <Text>Identify the missing runtime file; verify HTTPS and hostname checks remain enabled. Test the actual packaged artifact in an approved environment.</Text>
   <H2>Then test customer installation</H2>
   <Text>Clean SAC-on Windows first install; update from 3.6; login/reboot startup; pairing and journal preservation; complete dependency set; managed-device policy case.</Text>
   <H2>Finally test the purchase task</H2>
   <Text>Message → native protocol 10 context → compact proposal → corrections → reload → final review. Posting remains separately authorised.</Text>
   <Text>These are required acceptance checks, not tests completed by this research. No promise that every Windows policy accepts every release.</Text>
  </>}
  {view==='Sources'&&<>
   <H2>Official first, community cross-checks</H2>
   {sources.map(([label,url])=><Link key={url} href={url}>{label}</Link>)}
   <Text>The companion brief contains the full 25-source register, local evidence and caveats. Some old Reddit advice conflicts with current Microsoft guidance.</Text>
  </>}
 </Stack>;
}
