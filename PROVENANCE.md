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
| DSH_BRIEFING.md | 38bdc1048d5c746f2a39bf497974b580232470f687de98e35bf765aed6e54306 |
| LICENSE | 67f197131d4f84bb2d89b7f164a5672a6c4d07488bc884a83541eeb4d550923c |
| METHODS.md | cab529707304ec03a8cd92a4fc6f405d92b0c5323665b976409190b0354d1e20 |
| NOTICE | 57f64e39e6a87d47a44223ead6024bb061a00de459e90b1d18e990d066ff4c61 |
| PROJECT_BOOK.md | fb24a969597d2d89069f8e5f685aa327422b16be72f3d1f394259893957b1f36 |
| README.md | 8cdb619561fce0d2f0c4e11862f3196e5eab045f339becbe2179a5115f9fcff5 |
| astock_monitor/__init__.py | 72419c274eaa378b26ac16c5283c669dfcbd73dee8bc5291c2a5cab12db07667 |
| astock_monitor/alpha_lite.py | 58570de90dda732561356df3486a0453cfa771d90e0a88ffbc60badb1a44e9fb |
| astock_monitor/audit.py | 91eeb5c2a4cede178dc1b267b6f10a7d52dc798aa39b81dadce933c2ca64c44e |
| astock_monitor/calendar.py | cb29fc53a7055109240f17bc5a1902e4a476afa8bdd0cbbb53102e43b933483c |
| astock_monitor/cli.py | d8daad3a9c6796ca2c6ba9aa17b8df898e83e1102e425d79b5691298c670af13 |
| astock_monitor/collect.py | a468b47afa1db84bafaf1384a8618fb8e480402790f5dd60d5d20494e429c0c3 |
| astock_monitor/config.py | 9cf4c715f34a351c845162a0493d03a102a642b55a6e33362826aa7f1cccd1f6 |
| astock_monitor/doctor.py | 8e7d3fae308db2d8f7ac8e756a7e12c903ef874af4e9579e0e77c0b9bf89dc18 |
| astock_monitor/forecast.py | 78260362c3b7958573da39d4f092cd8968d94fc77bc8f616a22ced2c51b51791 |
| astock_monitor/limits.py | cdc153a034fb0f529ea3773b398284bc472afaee8e1f8bc4965e863955517fa1 |
| astock_monitor/metamdl.py | eb11c3e9b6ce3e22719b3bf3f99fdc576a64659786afb7144f86b20bdf5e171a |
| astock_monitor/notify_proactive.py | 37a5b81467b7c780efdd43cc277f7fae03f159308f383bc0f7c4e8a099d2ae39 |
| astock_monitor/portfolio.py | 7003c0d5f25302d6e9b92c0c7decd1c2d3c9f95002d369c02d6380b8284bdef7 |
| astock_monitor/regime.py | fb9bfae4d100781c339fe196c777cdb5667032eb3c034fbba2301c10ae6459c4 |
| astock_monitor/report.py | 6b02cf819b737a23166c6436b2f7de6d68a6554625f0aa7219e85a679fc852b3 |
| astock_monitor/riskfactors.py | 15a49add05c98fee78cb970256de90940cb5732adb5d3b6164d3cc24bd72ece8 |
| astock_monitor/sentiment.py | 46079c28d1ee60837049e78a473e66d83621b111e2c43a8aa1ab9c0a84c87569 |
| astock_monitor/signals.py | a2781175e9867c43cb525e57400a261035a6f740de3c1dae723d54cb38eea5dc |
| astock_monitor/store.py | 4d820fa2d244937188c8d92dcafc68b959da2f70cb792d1c6850929a4ee2fff9 |
| astock_monitor/triggers.py | 94d63708babd90e4d2748068ae16ac801392b390df39da68ea7726bb7af33b07 |
| config.json | 3ca1b4bc8b3042cf1468850896b6f5cc74f295f2227b8dbb34633e0c7564e37c |
| configs/cnequity.example.toml | b98a5b8a152162225a4dbb9e90a4606a5dad56ba18282afd3cc962b3cb432138 |
| docs/optimization-roadmap.md | fa34810877e07fd8eb26de03e3c7bc94bec1ca109437d8a147521e89d29bbbbb |
| docs/research/README.md | 99f932ac7644a86794dddc2191b2860e53a7f8a63b9792d5fc5b905ab24b05f6 |
| docs/week3-report.md | 1da7fe5ad369e6dfc81402f5612351a88c2d2d52f6ad2ae5563442a816e07b84 |
| results/alpha_ic_report.json | 45ca3ecb08b72a45e01d68156b261bc122fa59f96c9a09de6ed2906806aeeb9b |
| results/calendar_audit_verdict.json | 04b34706b8e62fa172cfec88a9bcca1afcdc3e71ab8a61d97899904c7ffd7f9b |
| results/combined_strategy.json | 0fca88fcf7dc59ce8d8e6ff82be84d0881310082157a7f38906ee5d263941400 |
| results/deep_analysis.json | 1bdef7da70ea0699206b7b759bb23e680fba71e3f37ee42973985c38f5d62efe |
| results/feature_ablation.json | b84e25fd12bb179467eeb239b1ff4780115316eed9f7b66a0ee61105be222f06 |
| results/final_combination.json | 7f5f2b069215e765e5cf9f7de2e4034526d275683d0cfd0252ecba225a788a25 |
| results/gated_strategy_sim.json | 1349cd8d1289f2c984798384d5b04a5a5b9d02334d09d16f44c2bedd30fdfb0e |
| results/hold_frac_scan.json | 77d058e5a4bb99129c239c49aa591e09bde628e219394f81f939d496484bc246 |
| results/lgbm_baseline.json | 81597562d7dff474cb4b9c3b189e6e92fa4a35c7bad700c87503380f932fb251 |
| results/lgbm_v2_comparison.json | b536fb75240c30ea110de73f3b01d8ff9cd7809d6497c07b3f04dbb4e0c0875e |
| results/lgbm_v3.json | 7922027d9eb04f49f512cfc468c98d6a2cecb7f71553f5dce13a1350a02c9e33 |
| results/lgbm_walkforward.json | b047f5653ed0d7ee848bb65001f7b8e88298c97f103e4248bbeefecd69287b14 |
| results/meta_v0.json | 508f074b66fddc106eda3b961f74d88a8af911a11870242b4f3dea6a0b343791 |
| results/poc4_rerun_verdict.json | 784a50633c350a5f8f55e5d7e8663b0feaedea7b4d7b50ad050c27a821690c7c |
| results/regime_audit_verdict.json | c83a297d0aff6c5ac27577a476dd5afd630eeeccf5eeece551861b1d481f1c47 |
| results/turnover_variants.json | 8af942d6e71ff7410e91e4fedf7653cf7f5fd57faeaa23b21987cef09ac06f59 |
| run_daily.bat | 3d69f0723ab232bf14fc1c2198e8bcfab15a715cf0f5ae0977f53abba52d677d |
| scripts/backfill_index_gap.py | 3b1b28551b63f8046088da7be39ae63aa84d56be7de4244a3d53d9bd0077d139 |
| scripts/build_dashboard.py | 41cadc99118c90c276d764ffcef8be59fd9ff0225c9c2d3fd9059cfed70f6431 |
| scripts/gh_api_push.py | 02c0685c6e3045cacfae85df295418da02e2e95c0f861cdb71f0869b4f7152e8 |
| scripts/provenance_check.py | c5a729c9fe1371f70108a08e7e2f6d724b4e042659c2182a772ee4d3c6ac560a |
| scripts/rebuild_breadth_history.py | 193576709533f76d738156cfa5f0ca937a30afd87cae5a395b5ca0b23f8fa8ad |
| scripts/verify/alpha_ic.py | bf89ebb8084375c58f95e738faa7f5460c0c4e332ee2a78545f5b0063348f924 |
| scripts/verify/calendar_audit.py | 727d6c864d5c0dff5bda521d3e7a52fd91d39467aceac92244b02a166411ba7b |
| scripts/verify/combined_final.py | 3db31a5732c6631bc22385ffdd372cf3b0e83eea994d766d79aafac2681188b8 |
| scripts/verify/combined_strategy.py | 88c8470d19bfc78b0136dd23ca92a396f44213a33f3bb473e2c9b0e3f4237980 |
| scripts/verify/crosscheck_sina.py | 458ed822246aca368fea771c517896d06178037ea3834a4a11368ac794c9d009 |
| scripts/verify/deep_analysis.py | 3d53be8ef321e23ebce5780810a8ea85c32fe275a19774e45569c523ea7b39f7 |
| scripts/verify/final_combination.py | 2668f31ce707a5fbb37a5f54972277fb4f09fa65a7288ee3da6506c92e2245bd |
| scripts/verify/gated_strategy_sim.py | 5ae0a123a80fa8678f59e7f397ce323db8253be9f3a02f511e53397f6ac1d5b6 |
| scripts/verify/lgbm_baseline.py | 8b111553577b5c093c1d28a5a6cd884a125d7572dc973559f11a423653f9af28 |
| scripts/verify/lgbm_v1_features.py | 201b5d81ed434c3a01de0f2d1cf910888ef1cad78752f55af863dbdb22632262 |
| scripts/verify/lgbm_v2.py | 13b8bd83c3ee043d0035be4230a53c32daac9100f72980684f84c56d2e7bafa6 |
| scripts/verify/lgbm_v3.py | 92465aa71dbb4d2f551a5c80ad9c895b82f0b84b8916bff485a150e63656865f |
| scripts/verify/lgbm_walkforward.py | 86e0b45be0512cdabeb78e9c40e13226dac8dfe25fd5285bbe9a5dad58dc6378 |
| scripts/verify/meta_v0.py | d500ba9c88423171fc818c22590373f078ecfd60098439b5fceafd5264bee08a |
| scripts/verify/poc4_rerun.py | 61e0975eccffd601ccd2e857bb3327e60d33a1eeea618e99c9263f4be055929c |
| scripts/verify/regime_audit.py | 36570676efbf9b0f20dd48bd4eb451528b524978321e9bfdc74fe644f4317557 |
| scripts/verify/storm_replay.py | fc29c27cb8f06672848b862ea81fad7849896634815ecdc8c40b576bf63baab3 |
| scripts/verify/turnover_variants.py | eeab4b6c613e6079b55b218e55dff0fee8577534c483d557a0c8b034ddf3562a |
| scripts/weekly_backup.bat | e76164175573ad9e197577e7024586118be2cb4b1275df7c56e3444e2ea3e6c5 |
| tests/__init__.py | 735469839c842bc3fbc34792d87ecca2fb190d80bc5c631024bb850a07b5bbfb |
| tests/test_alpha_lite.py | 7e8bd5541c7cbd374155f6b8e6d705cdeb19c87e5d069519b94fd03fbe9928ba |
| tests/test_audit.py | 4d829b366c05315df1cb813d5795383935661bc28a19d815b54b39ab92f12ead |
| tests/test_backfill.py | bb050acd9855a2e516e2763cfd2cf151c86b703ca4ae0f312230e134bc40bfd6 |
| tests/test_calendar.py | 8090b6a3f525079ee99598ccfd6730eb744117121c69971b51f4bc7200019459 |
| tests/test_collect.py | e4b2fe6e8d2173cb5f5d6bd6b8242a3bff2d719018f838cc37d799f6f289da82 |
| tests/test_doctor.py | 161d15596c5062e62de1c04349c821395b15ff94ae845ac6da95b1dd7fd4f4f6 |
| tests/test_forecast.py | f51c897fea19b76a317aa64e185bd5c0009d09d44ef7b6fb70e8290f35f43c5d |
| tests/test_limits.py | 11020024dcc3dc67564fec8772d6527148c2e5eef2f61e58ce46b8be103ffb21 |
| tests/test_metamdl.py | 91eab92c89fbc63ccb847aad605a49954afe85135da56191ca35beb10cc6d0d1 |
| tests/test_portfolio.py | 7341ee1077df8d01e02a1633a4633681b5c45a47f4bd3c2124ce3be777b50848 |
| tests/test_regime.py | be6988d45de0ac2299c8f0024075511f9726fb2bd170a982f1c0d4ebd9c600d5 |
| tests/test_report.py | ab935b23a0995ae986995c14db8c22823eaf9a045355b8b3465c92a4d7f1caeb |
| tests/test_riskfactors.py | f665a20bc1193d115b52ff5951b603f31c156dd871d96f44e147154c89206869 |
| tests/test_signal_context.py | 15e422d7cbb9d5846d7988a0d0d020d4f5ffe047bc67f548dc9611c8a02e8852 |
| tests/test_signals.py | 709f1f00b308de2fe55f93d3b973727f0b91cbd51593a30765c345faf07be439 |
| tests/test_store.py | 0300183a2f635953d6eafd80ef76de226566dc9633a10509164a35704cae5b40 |
| tests/test_triggers.py | 74855b3c4c2f7acd64fba4b0561a57308de8e4654b5297185fd02308806f52e4 |
--> /MANIFEST