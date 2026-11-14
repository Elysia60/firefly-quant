# PROVENANCE · 防伪溯源清单

> 本文件由发布流程生成:记录发布时全部跟踪文件的 SHA256。
> 任何副本若与此清单不符(且无法说明修改理由),即为未授权篡改或抄袭副本。
> 验证方法:`python scripts/provenance_check.py`(对每个文件重算 SHA256 并比对)。

- 发布版本:**v0.2.0「萤火」Firefly**
- 发布日期:2026-11-14
- 官方出处:github.com/Elysia60/firefly-quant
- 签名基准:本文件的 SHA256 自身不计入清单(清单由 git tag 固定)

## 文件清单(SHA256)

<!-- MANIFEST 由 provenance_check.py --write 生成,勿手改
| 文件 | SHA256 |
|---|---|
| .gitignore | 52cd3b2667e0212abecdb0053eee90d7541ebb80381a1416e00a129ded594ead |
| LICENSE | 67f197131d4f84bb2d89b7f164a5672a6c4d07488bc884a83541eeb4d550923c |
| METHODS.md | 419f23df5501179e3d285f0e653b744940640a6745c0b09f8bd1b6b658fbe857 |
| NOTICE | 57f64e39e6a87d47a44223ead6024bb061a00de459e90b1d18e990d066ff4c61 |
| PROJECT_BOOK.md | b8f8740f42c6aa829192b9391589044638747f23f81b9acc8ad6f4c874741849 |
| README.md | 8cdb619561fce0d2f0c4e11862f3196e5eab045f339becbe2179a5115f9fcff5 |
| astock_monitor/__init__.py | 72419c274eaa378b26ac16c5283c669dfcbd73dee8bc5291c2a5cab12db07667 |
| astock_monitor/alpha_lite.py | 58570de90dda732561356df3486a0453cfa771d90e0a88ffbc60badb1a44e9fb |
| astock_monitor/audit.py | 91eeb5c2a4cede178dc1b267b6f10a7d52dc798aa39b81dadce933c2ca64c44e |
| astock_monitor/calendar.py | cb29fc53a7055109240f17bc5a1902e4a476afa8bdd0cbbb53102e43b933483c |
| astock_monitor/cli.py | 36afd969118c90c2cb0be12865825c9ca9de946435b925c2705d355142a3dce5 |
| astock_monitor/collect.py | 8b7c26a775f6d53b70d1dec7b728cad7c6d342ca4a5e22b468309f596b6dc43d |
| astock_monitor/config.py | 9cf4c715f34a351c845162a0493d03a102a642b55a6e33362826aa7f1cccd1f6 |
| astock_monitor/doctor.py | 8e7d3fae308db2d8f7ac8e756a7e12c903ef874af4e9579e0e77c0b9bf89dc18 |
| astock_monitor/forecast.py | 78260362c3b7958573da39d4f092cd8968d94fc77bc8f616a22ced2c51b51791 |
| astock_monitor/limits.py | cdc153a034fb0f529ea3773b398284bc472afaee8e1f8bc4965e863955517fa1 |
| astock_monitor/metamdl.py | eb11c3e9b6ce3e22719b3bf3f99fdc576a64659786afb7144f86b20bdf5e171a |
| astock_monitor/regime.py | fb9bfae4d100781c339fe196c777cdb5667032eb3c034fbba2301c10ae6459c4 |
| astock_monitor/riskfactors.py | 15a49add05c98fee78cb970256de90940cb5732adb5d3b6164d3cc24bd72ece8 |
| astock_monitor/sentiment.py | f667192aaf5fd91ac881f987c26137920e89322a9427f9c8b1e863b811e6e285 |
| astock_monitor/signals.py | f655952f3c277ac2391eebb9de423d4a861a5ebab9d8c1bc2adb5ccb99857622 |
| astock_monitor/store.py | 4d820fa2d244937188c8d92dcafc68b959da2f70cb792d1c6850929a4ee2fff9 |
| config.json | 57a212072c9b4336229820b1336a38c27f5cb6edfa6b9190aea7e8baf40453b1 |
| configs/cnequity.example.toml | b98a5b8a152162225a4dbb9e90a4606a5dad56ba18282afd3cc962b3cb432138 |
| docs/optimization-roadmap.md | fa34810877e07fd8eb26de03e3c7bc94bec1ca109437d8a147521e89d29bbbbb |
| docs/research/README.md | 99f932ac7644a86794dddc2191b2860e53a7f8a63b9792d5fc5b905ab24b05f6 |
| docs/week3-report.md | 1da7fe5ad369e6dfc81402f5612351a88c2d2d52f6ad2ae5563442a816e07b84 |
| results/alpha_ic_report.json | 45ca3ecb08b72a45e01d68156b261bc122fa59f96c9a09de6ed2906806aeeb9b |
| results/calendar_audit_verdict.json | 04b34706b8e62fa172cfec88a9bcca1afcdc3e71ab8a61d97899904c7ffd7f9b |
| results/gated_strategy_sim.json | 1349cd8d1289f2c984798384d5b04a5a5b9d02334d09d16f44c2bedd30fdfb0e |
| results/lgbm_baseline.json | 81597562d7dff474cb4b9c3b189e6e92fa4a35c7bad700c87503380f932fb251 |
| results/meta_v0.json | 508f074b66fddc106eda3b961f74d88a8af911a11870242b4f3dea6a0b343791 |
| results/poc4_rerun_verdict.json | 784a50633c350a5f8f55e5d7e8663b0feaedea7b4d7b50ad050c27a821690c7c |
| results/regime_audit_verdict.json | c83a297d0aff6c5ac27577a476dd5afd630eeeccf5eeece551861b1d481f1c47 |
| run_daily.bat | 3d69f0723ab232bf14fc1c2198e8bcfab15a715cf0f5ae0977f53abba52d677d |
| scripts/build_dashboard.py | 41cadc99118c90c276d764ffcef8be59fd9ff0225c9c2d3fd9059cfed70f6431 |
| scripts/provenance_check.py | c5a729c9fe1371f70108a08e7e2f6d724b4e042659c2182a772ee4d3c6ac560a |
| scripts/verify/alpha_ic.py | bf89ebb8084375c58f95e738faa7f5460c0c4e332ee2a78545f5b0063348f924 |
| scripts/verify/calendar_audit.py | 727d6c864d5c0dff5bda521d3e7a52fd91d39467aceac92244b02a166411ba7b |
| scripts/verify/crosscheck_sina.py | 458ed822246aca368fea771c517896d06178037ea3834a4a11368ac794c9d009 |
| scripts/verify/gated_strategy_sim.py | 5ae0a123a80fa8678f59e7f397ce323db8253be9f3a02f511e53397f6ac1d5b6 |
| scripts/verify/lgbm_baseline.py | 8b111553577b5c093c1d28a5a6cd884a125d7572dc973559f11a423653f9af28 |
| scripts/verify/meta_v0.py | d500ba9c88423171fc818c22590373f078ecfd60098439b5fceafd5264bee08a |
| scripts/verify/poc4_rerun.py | 61e0975eccffd601ccd2e857bb3327e60d33a1eeea618e99c9263f4be055929c |
| scripts/verify/regime_audit.py | 36570676efbf9b0f20dd48bd4eb451528b524978321e9bfdc74fe644f4317557 |
| tests/__init__.py | 735469839c842bc3fbc34792d87ecca2fb190d80bc5c631024bb850a07b5bbfb |
| tests/test_alpha_lite.py | 7e8bd5541c7cbd374155f6b8e6d705cdeb19c87e5d069519b94fd03fbe9928ba |
| tests/test_audit.py | 4d829b366c05315df1cb813d5795383935661bc28a19d815b54b39ab92f12ead |
| tests/test_backfill.py | bb050acd9855a2e516e2763cfd2cf151c86b703ca4ae0f312230e134bc40bfd6 |
| tests/test_calendar.py | 8090b6a3f525079ee99598ccfd6730eb744117121c69971b51f4bc7200019459 |
| tests/test_collect.py | acc1086e7de965479aaa23499df096b25093e615632b7fc144e2a1f0a66a90c4 |
| tests/test_doctor.py | 161d15596c5062e62de1c04349c821395b15ff94ae845ac6da95b1dd7fd4f4f6 |
| tests/test_forecast.py | f51c897fea19b76a317aa64e185bd5c0009d09d44ef7b6fb70e8290f35f43c5d |
| tests/test_limits.py | 11020024dcc3dc67564fec8772d6527148c2e5eef2f61e58ce46b8be103ffb21 |
| tests/test_metamdl.py | 91eab92c89fbc63ccb847aad605a49954afe85135da56191ca35beb10cc6d0d1 |
| tests/test_regime.py | be6988d45de0ac2299c8f0024075511f9726fb2bd170a982f1c0d4ebd9c600d5 |
| tests/test_riskfactors.py | f665a20bc1193d115b52ff5951b603f31c156dd871d96f44e147154c89206869 |
| tests/test_signals.py | 709f1f00b308de2fe55f93d3b973727f0b91cbd51593a30765c345faf07be439 |
| tests/test_store.py | 0300183a2f635953d6eafd80ef76de226566dc9633a10509164a35704cae5b40 |
--> /MANIFEST