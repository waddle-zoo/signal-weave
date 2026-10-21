# Research archive move and source-hash manifest

Source SHA-256 values were recorded immediately before relocation. Archive
SHA-256 values were recorded after relocation and link repair. The legacy
guide was not rewritten and its archived digest equals its source digest
exactly.

| Source path | Destination path | Source SHA-256 | Archive SHA-256 |
|---|---|---|---|
| `origin/main@437ab297:docs/evaluations.md` | `docs/archive/research/evaluations-2026-10-20.md` | `517fc456614c9111b6ae83225e419d91e261676d6a2a6a7f4a8522d1274e3980` | `517fc456614c9111b6ae83225e419d91e261676d6a2a6a7f4a8522d1274e3980` |
| `docs/evaluation.md` | `docs/archive/research/evaluation-legacy.md` | `ae67ed7e2977f944cdd01a6a4023a83bcd24119591ffeee003ef6de5891de6af` | `ae67ed7e2977f944cdd01a6a4023a83bcd24119591ffeee003ef6de5891de6af` |
| `docs/everything-tracking-trial.md` | `docs/archive/research/everything-tracking-trial.md` | `594fe7c79f74f290eee168fdacf2f7f27e03296460f4b2e5395becd41fe6f1e8` | `62ac31009486b669d87421b102498b3cb3d5e9387ff369b028e2d70bc217fe06` |
| `docs/everything-tracking-llm-benchmark.md` | `docs/archive/research/everything-tracking-llm-benchmark.md` | `7d3e05163da35826de671686df3291e8c8f33b0dfc493486a544c02b1b1845c9` | `25fac021bd2d7e26885a38ed3b7675cde7af040b0adc7e0432d5385f54ab727f` |
| `docs/mass-analytical-trial.md` | `docs/archive/research/mass-analytical-trial.md` | `51aa677238733f454351401e00e040efd37039df74c9f3c1a27e1e3b64d2b3e5` | `03579d11ff58e6beade9f4a7752befdc1d909bf1137d5c507d40b88a60f47ee5` |
| `docs/northstar-corporation-trial.md` | `docs/archive/research/northstar-corporation-trial.md` | `8114d94a711de234e1a029be13b8d63afebcc165c1485f46ea26742e8fd6179e` | `f3ec29d0a25902e8f18fa09ea9fdf7c88ce9fed22619db372c368807475f17c9` |
| `docs/northstar-scale-trial.md` | `docs/archive/research/northstar-scale-trial.md` | `8bc274deee401cbf0cd6d88829c62b619c623d371b26ce72eca1864e74ad2d4f` | `8bc274deee401cbf0cd6d88829c62b619c623d371b26ce72eca1864e74ad2d4f` |
| `docs/northstar-longitudinal-panel-trial.md` | `docs/archive/research/northstar-longitudinal-panel-trial.md` | `c959cc0b3b58701ae30443a1f9d5a3c83fb70670b5cbd8f678062708f0fc0b0c` | `dfe9639ad4238a3a38d75dfcf06973361e117b4d7b9e9594f6dfa8f72ade30f7` |
| `tests/test_everything_tracking_trial.py` | `evaluations/tests/historical/test_everything_tracking_trial.py` | `518e07a12207b762ece01cb73a3329bed2ce0a1742b6d978df8841322b74cc6e` | `518e07a12207b762ece01cb73a3329bed2ce0a1742b6d978df8841322b74cc6e` |
| `tests/test_everything_tracking_card_clarity_trial.py` | `evaluations/tests/historical/test_everything_tracking_card_clarity_trial.py` | `892f9d9d366ae91aecbbf7c4687aa7f54851b4afafe1ce1df656bbe9f34391a5` | `892f9d9d366ae91aecbbf7c4687aa7f54851b4afafe1ce1df656bbe9f34391a5` |
| `tests/test_everything_tracking_llm_benchmark.py` | `evaluations/tests/historical/test_everything_tracking_llm_benchmark.py` | `a08737eb5c3a96681603f8eb9dc29589310c2b6fd6e65900f53a9a44d829d84d` | `a08737eb5c3a96681603f8eb9dc29589310c2b6fd6e65900f53a9a44d829d84d` |
| `tests/test_mass_analytical_trial.py` | `evaluations/tests/historical/test_mass_analytical_trial.py` | `1cdfabaad2e216c983d7612f488889cb6be87719e1509c2709c2651f2f208510` | `1cdfabaad2e216c983d7612f488889cb6be87719e1509c2709c2651f2f208510` |
| `tests/test_northstar_corporation_trial.py` | `evaluations/tests/historical/test_northstar_corporation_trial.py` | `96cb326a962cfb7cd0b5b810e1bb501458d9f1bd50678de8e87878b11bd0db77` | `96cb326a962cfb7cd0b5b810e1bb501458d9f1bd50678de8e87878b11bd0db77` |
