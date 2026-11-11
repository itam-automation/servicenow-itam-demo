# License position

Check on 2026-11-11 with `python3 loader/check_license_position.py` (read only).

**9 of 9 license positions match the ground truth.** The position calculated by ServiceNow (script include `ItamLicensePosition`, table `u_itam_license_position`, read via `GET /license_position`) and the independent recalculation from the raw instance data agree.

| | |
|---|---|
| Installations on Muster AG devices | 582 (ground truth: 582) |
| Software packages in use (raw name + version) | 26 |
| Licensed or license-relevant software models | 9 |
| Licenses (`alm_license`) | 8 |
| Position calculated in ServiceNow | matches (calculated 2026-11-11 08:22:31 UTC) |

| Product | Publisher | Metric | Rights | Usage | Difference | Status |
|---|---|---|---:|---:|---:|---|
| WinRAR | win.rar GmbH | Per workstation | 0 | 10 | -10 | no license |
| Acrobat Pro | Adobe | Per named user | 20 | 24 | -4 | under-licensed |
| Visio Plan 2 | Microsoft | Per named user | 9 | 11 | -2 | under-licensed |
| PyCharm Professional | JetBrains | Per named user | 5 | 6 | -1 | under-licensed |
| AutoCAD LT | Autodesk | Per named user | 8 | 8 | +0 | balanced |
| Project Professional 2021 | Microsoft | Per workstation | 1 | 0 | +1 | unused (shelfware) |
| Snagit | TechSmith | Per named user | 13 | 11 | +2 | over-licensed |
| Photoshop | Adobe | Per named user | 13 | 10 | +3 | over-licensed |
| Microsoft 365 Apps for enterprise | Microsoft | Per named user | 94 | 89 | +5 | over-licensed |

Counting rules (simplified, same as the generator): *Per workstation* counts devices with at least one installation; *Per named user* counts distinct assigned users of those devices, a device without a user counts once. Free software without a license is left out.
