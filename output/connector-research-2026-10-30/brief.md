# Philixa connector research — 30 October 2026, India

## Seedha answer

Windows connector ko **Smart App Control (SAC)** ke through rok raha hai. Yeh sirf browser download warning nahi hai. Hamare blocked-file events ka policy ID Microsoft ke published SAC enforcement policy se exactly match karta hai. Laptop company-managed hona is wording se prove nahi hota. [Microsoft policy catalogue](https://learn.microsoft.com/en-us/windows/security/application-security/application-control/app-control-for-business/operations/inbox-appcontrol-policies)

SAC unfamiliar unsigned code ko reject kar sakta hai; recognized code ya trusted publisher signature is trust decision ka part hai. Yeh apne aap malware detection ka proof nahi. SAC ke liye individual app ka ordinary Allow button supported nahi hai. Isliye pehle suggest ki gayi generic “admin se ek app approve kara lo” advice is personal-PC case mein reliable answer nahi thi. [SAC overview](https://learn.microsoft.com/en-us/windows/apps/develop/smart-app-control/overview), [Microsoft FAQ](https://support.microsoft.com/en-us/windows/security/threat-malware-protection/smart-app-control-frequently-asked-questions)

## Local evidence, inference aur unknown alag hain

- **Confirmed:** Code Integrity 3077/3033 events name the Philixa installer and policy `{0283ac0f-fff1-49ae-ada1-8a933130cad6}`. Authenticode status was `NotSigned`.
- **Confirmed today:** `VerifiedAndReputablePolicyState = 1`, consistent with enforcement. `CiTool -lp -json` was denied access, so it did not produce a complete policy inventory. Registry state plus exact logged GUID and Microsoft's catalogue support the SAC diagnosis.
- **Confirmed earlier:** packaged HTTPX client initialization returned `FileNotFoundError`. Groq extraction and direct Tally history passed after VPN was disconnected. Those are separate observations; this research did not retest provider access.
- **Not confirmed:** which exact file HTTPX could not find. CA data/runtime resolution is a plausible candidate, not a proved root cause. The local PyInstaller build manifest already lists `certifi/cacert.pem`, so simply saying “we forgot to include the certificate file” goes beyond the evidence.
- **Not confirmed:** the latest CA-path source fix works inside the executable. Source TLS tests passed; Windows blocked packaged acceptance. No new connector executable was run or security policy changed for this research.

HTTPX normally uses certifi roots and permits an explicit validating SSL context. PyInstaller one-file applications resolve packaged data from an extracted runtime directory; source execution is not a substitute for that runtime test. Fix the actual resource resolution and keep certificate/hostname validation enabled. [HTTPX SSL](https://www.python-httpx.org/advanced/ssl/), [PyInstaller runtime paths](https://pyinstaller.org/en/stable/runtime-information.html), [official certifi collection hook](https://github.com/pyinstaller/pyinstaller-hooks-contrib/blob/master/_pyinstaller_hooks_contrib/stdhooks/hook-certifi.py)

## GitHub aur Reddit ka result

PyInstaller's own issue **#6747**, opened in 2022 and still open when checked, discusses SAC and unsigned extracted modules. This is an established distribution problem, not a special Philixa/Tally limitation. Reports disagree on which outer/inner signing combinations suffice; do not treat one successful machine as a universal result. Microsoft's guidance to cover application binaries is stronger than anecdotal shortcuts. [PyInstaller #6747](https://github.com/pyinstaller/pyinstaller/issues/6747), [Microsoft application signing guidance](https://learn.microsoft.com/en-us/windows/security/book/application-security-application-and-driver-control)

Reddit reports corroborate unsigned-Python distribution friction and regional signing difficulties. Some posts still claim EV signing instantly removes SmartScreen prompts. Current Microsoft guidance explicitly contradicts that claim. Reddit is useful for finding failure modes; official current docs decide the recommendation. [Python discussion](https://www.reddit.com/r/Python/comments/1ufer3u/windows_defender_blocks_python_executables/), [solo developer discussion](https://www.reddit.com/r/dotnet/comments/1vpzzf9/solo_devs_shipping_windows_apps_is_code_signing/), [current SmartScreen guidance](https://learn.microsoft.com/en-us/windows/apps/package-and-deploy/smartscreen-reputation)

## Supported routes, with actual trade-offs

### A. Microsoft Store-distributed MSIX — first feasibility check for our limited budget

Store-distributed MSIX receives Store signing; registration is currently free. Raw EXE/MSI Store submission still requires publisher signing, so uploading the same unsigned EXE is not the answer. Account type, identity verification, Store policy and certification still apply. Free registration is not a promise of acceptance or zero engineering cost. [Store signing guide](https://learn.microsoft.com/en-us/windows/msix/package/sign-msix-package-guide), [publish guide](https://learn.microsoft.com/en-us/windows/apps/package-and-deploy/publish-first-app), [current account requirements](https://learn.microsoft.com/en-us/windows/apps/publish/partner-center/open-a-developer-account)

**Our inference/recommendation:** evaluate this before buying a certificate. Philixa currently uses a scheduled startup task, per-user credentials/settings, SQLite journal, executable replacement and bundled Node/MCP. Startup, storage migration, child processes and update behaviour need a compatibility test; changing the extension to `.msix` is insufficient. No feasibility or Store approval has been established yet. [MSIX preparation](https://learn.microsoft.com/en-us/windows/msix/desktop/desktop-to-uwp-prepare)

### B. Direct EXE distribution — publicly trusted code signing

Use an eligible trusted signing provider, timestamp releases, validate signatures and test the complete installed binary/dependency set. This addresses publisher trust; it does not fix the HTTPX resource error. Valid signing also does not promise no SmartScreen reputation warning on every fresh release. Do not pay an EV premium solely for an obsolete instant-reputation claim. [SAC signing](https://learn.microsoft.com/en-us/windows/apps/develop/smart-app-control/code-signing-for-smart-app-control), [SmartScreen reputation](https://learn.microsoft.com/en-us/windows/apps/package-and-deploy/smartscreen-reputation)

Azure Artifact Signing Public Trust is **not presently listed as available to individual developers in India**: the current individual eligibility is US/Canada; India is also absent from the listed organization countries. Private Trust does not equal public trust on arbitrary customer PCs. Azure student credits alone do not establish eligibility. [Azure prerequisites](https://learn.microsoft.com/en-us/azure/artifact-signing/quickstart), [trust models](https://learn.microsoft.com/en-us/azure/artifact-signing/concept-trust-models)

### C. Open-source signing assistance — conditional, not a shortcut

SignPath Foundation can help qualifying genuine open-source projects, but its rules include an OSI-approved license, no proprietary components and other project requirements. Do not assume a proprietary commercial connector qualifies or change licensing merely to evade those conditions. No application or eligibility assessment was made. [Foundation terms](https://signpath.org/terms)

## What should happen next

1. Keep SAC, TLS verification and accounting permission gates intact. Do not use policy deletion, renamed executables, disabled protection or Python execution as a workaround for a blocked binary.
2. First assess Store/MSIX compatibility and correct account eligibility; choose direct signed distribution if Store constraints cannot support this connector.
3. Capture a sanitized full packaged transport traceback and resolved-resource existence evidence in an approved test environment. Verify the exact missing file before declaring the CA change a fix.
4. Test install, same-user startup, logoff/reboot, pairing and journal retention, native protocol 10 reads, HTTPS, updates and uninstall on clean supported Windows systems. Include SAC-on first install, an update from 3.6 and a managed-device case.
5. Then test message → native context → compact proposal → grouped corrections → reload → final review. Posting acceptance remains separately authorised. Publish only the artifact/hash that passed.

**Research conclusion:** there are supported distribution solutions today. None proves the current connector is fixed or that every Windows configuration will accept it. Signing/trust and missing runtime resources are two separate engineering tracks. This task researched them; it did not enable the feature or publish an installer.

## Curated source register (25 sources)

Official/maintainer evidence was prioritized. Community reports were cross-checked and are not acceptance tests. This is a focused deep investigation, not a claim to have read every GitHub issue or Reddit post.

1. [Microsoft inbox policy IDs](https://learn.microsoft.com/en-us/windows/security/application-security/application-control/app-control-for-business/operations/inbox-appcontrol-policies)
2. [Smart App Control overview](https://learn.microsoft.com/en-us/windows/apps/develop/smart-app-control/overview)
3. [Smart App Control FAQ](https://support.microsoft.com/en-us/windows/security/threat-malware-protection/smart-app-control-frequently-asked-questions)
4. [SAC signing compliance](https://learn.microsoft.com/en-us/windows/apps/develop/smart-app-control/code-signing-for-smart-app-control)
5. [SAC application testing](https://learn.microsoft.com/en-us/windows/apps/develop/smart-app-control/test-your-app-with-smart-app-control)
6. [Windows application/driver control](https://learn.microsoft.com/en-us/windows/security/book/application-security-application-and-driver-control)
7. [SmartScreen reputation](https://learn.microsoft.com/en-us/windows/apps/package-and-deploy/smartscreen-reputation)
8. [MSIX signing guide](https://learn.microsoft.com/en-us/windows/msix/package/sign-msix-package-guide)
9. [Publish a first Windows app](https://learn.microsoft.com/en-us/windows/apps/package-and-deploy/publish-first-app)
10. [Store account requirements](https://learn.microsoft.com/en-us/windows/apps/publish/partner-center/open-a-developer-account)
11. [Store registration announcement](https://blogs.windows.com/windowsdeveloper/2025/09/10/free-developer-registration-for-individual-developers-on-microsoft-store/)
12. [Artifact Signing regional prerequisites](https://learn.microsoft.com/en-us/azure/artifact-signing/quickstart)
13. [Artifact Signing trust models](https://learn.microsoft.com/en-us/azure/artifact-signing/concept-trust-models)
14. [HTTPX SSL configuration](https://www.python-httpx.org/advanced/ssl/)
15. [HTTPX environment handling](https://www.python-httpx.org/environment_variables/)
16. [PyInstaller runtime data paths](https://pyinstaller.org/en/stable/runtime-information.html)
17. [PyInstaller SAC issue #6747](https://github.com/pyinstaller/pyinstaller/issues/6747)
18. [PyInstaller TLS issue #7229](https://github.com/pyinstaller/pyinstaller/issues/7229) — related SSL symptom on another platform; not proof of our exact error.
19. [Maintained certifi data hook](https://github.com/pyinstaller/pyinstaller-hooks-contrib/blob/master/_pyinstaller_hooks_contrib/stdhooks/hook-certifi.py)
20. [Reddit: unsigned Python executables](https://www.reddit.com/r/Python/comments/1ufer3u/windows_defender_blocks_python_executables/)
21. [Reddit: outside-US/Canada signing concerns](https://www.reddit.com/r/Windows11/comments/1pz8qww/windows_code_signing_is_broken_for_indie/)
22. [Reddit: India Artifact Signing report](https://www.reddit.com/r/AZURE/comments/1slc8p3/azure_trusted_signing_suddenly_broken_for_india/)
23. [Reddit: solo-developer signing experience](https://www.reddit.com/r/dotnet/comments/1vpzzf9/solo_devs_shipping_windows_apps_is_code_signing/)
24. [SignPath Foundation conditions](https://signpath.org/terms)
25. [Desktop-app MSIX preparation](https://learn.microsoft.com/en-us/windows/msix/desktop/desktop-to-uwp-prepare)
