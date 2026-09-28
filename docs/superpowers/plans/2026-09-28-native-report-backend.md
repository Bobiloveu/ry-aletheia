# Mobile 原生报告 Backend 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (- [ ]) syntax for tracking.

**Goal:** 让 Backend 为新旧测试与验收报告提供经验证的原生报告、历史轨迹、冻结底图与分页样本 API，供现有 Flutter Mobile 原生页面直接消费。

**Architecture:** 新增 NativeReportArchive 作为唯一受控归档边界：它从既有结构化轨迹 JSON 与验收资产清单读取数据，生成原子写入的 sidecar 和冻结 PNG，不解析 HTML/SVG，也不访问当前运行时地图。RunManager 与 AcceptanceReportWriter 在新报告落盘后调用它；ConsoleHandler 只通过归档读取索引增量和只读 API，启动后的低优先级 worker 分批回填历史报告。

**Tech Stack:** Python 3.10、标准库 json/threading/secrets/base64/pathlib、既有 PGM→PNG 工具、pytest（Pixi）、Flutter/Dart（锁定 FVM，仅验证既有消费者）。

**Spec:** docs/superpowers/specs/2026-09-28-native-report-backend-design.md

## Global Constraints

- 只允许 Backend 控制 ROS、任务、报告与运行时文件；Mobile 只走 HTTP，新增接口不得调用 ROS 或控制服务。
- 原生归档只可读取 run_<12 hex>_trajectory 中的结构化 JSON、其中由新采集阶段写入的同级冻结 PNG，以及验收报告 .assets.json 中列出的受控轨迹目录；禁止解析 HTML、CSV 或 SVG，禁止从当前 Observation/Deployment 重新推断历史地图。历史记录没有独立 PNG 时可回填摘要/任务，但其轨迹引用必须为 unavailable。
- 所有 public ID 均为 Backend 签发的不透明 [A-Za-z0-9_-]{1,128} token；JSON 不得返回文件名、路径、URL、HTML、CSV、SVG、原始 ROS 数据、凭据或未受控现场数据。
- 归档 JSON/PNG 必须先写同目录临时文件、fsync 后 os.replace；不完整或验证失败的归档不能进入报告索引。
- GET /api/reports 的 Existing 字段和 HTML/CSV/filename 删除语义不变；PC Web 不消费 native_report，不改动报告 UI。
- 新端点只读；格式错误的 ID/cursor/limit 返回 400，格式正确但未知、已删除或跨报告的 ID 返回 404。
- 回填在监听 HTTP 后的单线程 daemon worker 内分批执行；不得在 GET 中回填、不得阻塞报告生成、测试执行或 HTTP 监听。
- 只在 Backend、PC 回归和锁定 FVM Mobile 检查全部通过后，把共享契约从 Planned 升级为 Existing，并记录三端验证证据。

---

## File Structure

- Create: autodrive_console/native_report_archive.py — 原生 sidecar schema v1、冻结 PNG/轨迹 JSON 源验证、原子 I/O、分页读取、历史候选枚举与删除联动。
- Modify: autodrive_console/trajectory_render.py — 从当前受控 PGM 生成独立冻结 PNG，严格校验 CachedMapAsset 元数据并原子落盘。
- Create: tests/test_native_report_archive.py — 归档源边界、schema、原子写入、分页、PNG、历史回填候选与安全删除的单元测试。
- Modify: autodrive_console/run_manager.py — 在 _write_trajectory 中从当前受控 PGM 写入独立冻结 PNG 与安全资源名，再在 HTML/CSV 完成后为新测试运行调用归档器；归档失败仅记录受控日志。
- Modify: autodrive_console/acceptance_report.py — 验收 HTML/CSV/assets manifest 完成后为新验收报告调用同一归档器；归档失败不回滚已有报告。
- Modify: web_console.py — 建立归档服务、启动受限回填 worker、索引增量、四个只读 native 路由、受限 PNG 响应和 filename 删除联动。
- Modify: tests/test_acceptance.py、tests/test_offline_modules.py — 覆盖验收/测试生产者、HTTP 路由、Existing 索引兼容、400/404、启动回填与删除联动。
- Modify: shared/contracts/task_execution.md、docs/backend/README.md — 仅在全量验证完成后发布 Existing 契约与运维说明。

## Interfaces

~~~python
class NativeReportArchiveError(ValueError):
    pass

class NativeReportNotFound(NativeReportArchiveError):
    pass

class NativeReportArchive:
    def __init__(self, report_dir: Path, *, max_png_bytes: int = 16 * 1024 * 1024,
                 max_map_cells: int = 16_000_000) -> None: pass
    def archive_test_report(self, *, html_filename: str, run: RunRecord) -> dict: pass
    def archive_acceptance_report(self, *, html_filename: str, plan: AcceptancePlan) -> dict: pass
    def archive_historic_report(self, html_filename: str) -> bool: pass
    def historic_filenames(self) -> list[str]: pass
    def summary_for_filename(self, html_filename: str) -> dict | None: pass
    def detail_page(self, report_id: str, cursor: str | None, limit: int) -> dict: pass
    def trajectory(self, report_id: str, trajectory_id: str) -> dict: pass
    def trajectory_map_png(self, report_id: str, trajectory_id: str) -> bytes: pass
    def sample_page(self, report_id: str, trajectory_id: str, cursor: str, limit: int) -> dict: pass
    def delete_for_filename(self, html_filename: str) -> None: pass
~~~

Sidecar 内部可保存受限资源名和完整样本；对 Mobile 的所有返回只允许 shared/contracts/task_execution.md 中定义的字段。所有 outward 方法仅对畸形请求抛出 NativeReportArchiveError；格式合法但资源不存在使用 NativeReportNotFound，使 HTTP 层稳定返回 404。

### Task 1: 建立受控归档 schema 和历史源读取

**Files:**
- Create: autodrive_console/native_report_archive.py
- Test: tests/test_native_report_archive.py

**Consumes:** RunRecord attempt/trajectory 字段、AcceptancePlan items、MapAssetCache 轨迹 JSON 布局，以及由 trajectory_render.freeze_map_png 生成的同级 PNG。

**Produces:** 可验证 schema v1 sidecar；源目录、JSON、地图元数据、有限坐标、文本长度和 PNG 尺寸的单一验证边界。新轨迹 JSON 中的冻结 PNG 仅由 RunManager 在采集时生成；历史 JSON 缺少该资源时仅能生成 unavailable 引用。

- [ ] **Step 1: 写出失败的来源边界与冻结测试**

~~~python
def test_archives_only_verified_trajectory_json_and_existing_frozen_png(tmp_path):
    reports = tmp_path / "reports"
    reports.mkdir()
    html = reports / "报告_20260928_100001_测试_123456789abc.html"
    html.write_text("legacy html must never be parsed", encoding="utf-8")
    _write_valid_trajectory_fixture(reports, run_id="123456789abc", attempt=1, frozen_map=True)

    archive = NativeReportArchive(reports)
    assert archive.archive_historic_report(html.name) is True
    native = archive.summary_for_filename(html.name)

    assert native is not None and native["schema_version"] == 1
    assert native["report_id"].startswith("rpt_")
    assert list((reports / ".native-reports").glob("*.png"))
    assert "legacy html" not in json.dumps(native, ensure_ascii=False)

def test_rejects_manifest_directory_escape(tmp_path):
    reports = tmp_path / "reports"
    reports.mkdir()
    html = reports / "acceptance_123456789abc_20260928_100001.html"
    html.write_text("ignored", encoding="utf-8")
    (reports / "acceptance_123456789abc_20260928_100001.assets.json").write_text(
        '{"schema":1,"trajectory_directories":["../outside"]}', encoding="utf-8"
    )
    assert NativeReportArchive(reports).archive_historic_report(html.name) is False

def test_historic_json_without_frozen_png_exposes_unavailable_trajectory(tmp_path):
    archive, summary = _archive_fixture_with_structured_history(tmp_path, frozen_map=False)
    page = archive.detail_page(summary["report_id"], None, 50)
    assert page["items"][0]["trajectory_refs"][0]["status"] == "unavailable"
~~~

- [ ] **Step 2: 运行失败测试**

Run: pixi run pytest tests/test_native_report_archive.py -q

Expected: FAIL，因为 native_report_archive 模块尚不存在。

- [ ] **Step 3: 实现最小、安全的归档边界**

~~~python
NATIVE_DIRNAME = ".native-reports"
TOKEN = re.compile(r"^[A-Za-z0-9_-]{1,128}$")
TRAJECTORY_DIRECTORY = re.compile(r"^run_[0-9a-f]{12}_trajectory$")

def _owned_child(root: Path, name: str) -> Path:
    candidate = (root / name).resolve()
    if candidate.parent != root.resolve() or candidate.is_symlink():
        raise NativeReportArchiveError("报告归档来源无效")
    return candidate

def _atomic_write(target: Path, body: bytes) -> None:
    temporary = target.with_name(f".{target.name}.{secrets.token_hex(8)}.tmp")
    try:
        with temporary.open("xb") as handle:
            handle.write(body)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)
~~~

逐项验证轨迹 JSON 的地图 resolution/width/height/origin、坐标、virtual walls、理想/实际路线和样本。完整样本仅保存在 sidecar，display_paths 从同一批样本确定性抽样且单路径最多 2,000 点。只复制 JSON 声明、同级且非 symlink 的冻结 PNG，并校验尺寸/字节；不允许归档器读取 PGM 或当前地图。缺少 PNG 的历史段只生成 unavailable 引用，绝不提供详情/样本/地图端点。

- [ ] **Step 4: 运行并确认通过**

Run: pixi run pytest tests/test_native_report_archive.py -q

Expected: PASS。

- [ ] **Step 5: 提交归档基础**

~~~bash
git add autodrive_console/native_report_archive.py tests/test_native_report_archive.py
git commit -m "feat: archive native report evidence"
~~~

### Task 2: 增加稳定分页、资源读取与归档删除

**Files:**
- Modify: autodrive_console/native_report_archive.py
- Modify: tests/test_native_report_archive.py

**Consumes:** Task 1 完整 sidecar。

**Produces:** summary_for_filename、detail_page、trajectory、trajectory_map_png、sample_page、delete_for_filename；严格的 400/404 区分由异常类型承载。

- [ ] **Step 1: 写出失败的分页、越权与删除测试**

~~~python
def test_pages_samples_and_hide_internal_names(tmp_path):
    archive, summary = _archive_fixture_with_three_samples(tmp_path)
    page = archive.detail_page(summary["report_id"], None, 1)
    reference = page["items"][0]["trajectory_refs"][0]
    details = archive.trajectory(summary["report_id"], reference["trajectory_id"])
    samples = archive.sample_page(
        summary["report_id"], reference["trajectory_id"],
        details["samples_next_cursor"], 1,
    )

    assert page["next_cursor"] is not None
    assert [sample["sample_index"] for sample in samples["samples"]] == [0]
    assert archive.trajectory_map_png(summary["report_id"], reference["trajectory_id"]).startswith(b"\x89PNG\r\n\x1a\n")
    assert "run_" not in json.dumps([page, details, samples])

def test_valid_missing_and_cross_report_identifiers_are_not_found(tmp_path):
    archive, summary = _archive_fixture_with_three_samples(tmp_path)
    with pytest.raises(NativeReportNotFound):
        archive.trajectory(summary["report_id"], "traj_other_report")

def test_filename_delete_removes_only_backend_owned_native_payload(tmp_path):
    archive, _summary = _archive_fixture_with_three_samples(tmp_path)
    archive.delete_for_filename("报告_20260928_100001_测试_123456789abc.html")
    assert archive.summary_for_filename("报告_20260928_100001_测试_123456789abc.html") is None
    assert not list((tmp_path / "reports" / ".native-reports").glob("*"))
~~~

- [ ] **Step 2: 运行失败测试**

Run: pixi run pytest tests/test_native_report_archive.py -q

Expected: FAIL，因为 lookup、cursor 或删除方法未实现。

- [ ] **Step 3: 实现固定 cursor 和限制读取**

~~~python
def _encode_cursor(offset: int) -> str:
    return base64.urlsafe_b64encode(f"v1:{offset}".encode()).decode().rstrip("=")

def _decode_cursor(cursor: str) -> int:
    if not isinstance(cursor, str) or not cursor or len(cursor) > 512:
        raise NativeReportArchiveError("分页标识无效")
    padded = cursor + "=" * (-len(cursor) % 4)
    try:
        decoded = base64.urlsafe_b64decode(padded.encode("ascii")).decode("ascii")
    except (UnicodeEncodeError, UnicodeDecodeError, ValueError):
        raise NativeReportArchiveError("分页标识无效") from None
    if not re.fullmatch(r"v1:(0|[1-9][0-9]*)", decoded):
        raise NativeReportArchiveError("分页标识无效")
    return int(decoded.removeprefix("v1:"))

def sample_page(self, report_id: str, trajectory_id: str, cursor: str, limit: int) -> dict:
    trajectory = self._trajectory_record(report_id, trajectory_id)
    offset = _decode_cursor(cursor)
    samples = trajectory["samples"]
    return {
        "samples": samples[offset:offset + limit],
        "next_cursor": _encode_cursor(offset + limit) if offset + limit < len(samples) else None,
    }
~~~

detail limit 只能为 1..100，samples limit 只能为 1..1000。先验证 token/cursor/limit 再查询；合法 token 未命中、跨报告 trajectory 与已经删除资源均抛 NativeReportNotFound。删除仅删除由精确 HTML filename 关联的 sidecar/payload 目录，拒绝 symlink，且绝不删除现有的轨迹源证据目录。

- [ ] **Step 4: 运行归档测试**

Run: pixi run pytest tests/test_native_report_archive.py -q

Expected: PASS。

- [ ] **Step 5: 提交分页与所有权处理**

~~~bash
git add autodrive_console/native_report_archive.py tests/test_native_report_archive.py
git commit -m "feat: expose paged native report archive"
~~~

### Task 3: 让新测试和验收报告在落盘后归档

**Files:**
- Modify: autodrive_console/run_manager.py:1304-1365、1069-1077
- Modify: autodrive_console/trajectory_render.py:19-26、160-190
- Modify: autodrive_console/acceptance_report.py:148-236
- Modify: tests/test_offline_modules.py
- Modify: tests/test_acceptance.py

**Consumes:** Tasks 1–2 的 archive_test_report/archive_acceptance_report。

**Produces:** 新轨迹在 PGM 仍受控可用时写入独立冻结 PNG 和结构化安全资源名；每份成功落盘的测试或验收 HTML/CSV/assets 报告均尝试生成同一 schema v1 sidecar；归档失败不会破坏既有报告。

- [ ] **Step 1: 写出失败的两个 producer 集成测试**

~~~python
def test_new_trajectory_writes_frozen_png_before_report_archive(tmp_path):
    manager, run, assets = _completed_run_with_trajectory(tmp_path)
    trajectory_file = manager._write_trajectory(run, 1, run.attempts[0].trajectory, assets)
    saved = json.loads(trajectory_file.read_text(encoding="utf-8"))
    assert (trajectory_file.parent / saved["frozen_maps"][0]["filename"]).is_file()

def test_run_report_writes_native_sidecar_after_html_and_csv(tmp_path):
    manager, run = _completed_run_with_trajectory(tmp_path)
    manager._write_report(run)
    report = next((tmp_path / "reports").glob("*.html"))

    assert NativeReportArchive(tmp_path / "reports").summary_for_filename(report.name)
    assert report.with_suffix(".csv").is_file()

def test_acceptance_report_writes_native_sidecar_after_assets_manifest(tmp_path):
    plan = _terminal_plan_with_verified_trajectory(tmp_path)
    report = AcceptanceReportWriter(tmp_path / "reports").write(plan)

    assert (tmp_path / "reports" / report.asset_manifest_filename).is_file()
    assert NativeReportArchive(tmp_path / "reports").summary_for_filename(report.html_filename)
~~~

- [ ] **Step 2: 运行失败测试**

Run: pixi run pytest tests/test_offline_modules.py -k native_sidecar tests/test_acceptance.py -k native_sidecar -q

Expected: FAIL，因为两个 writer 都还未调用归档器。

- [ ] **Step 3: 在 legacy 报告完成后调用同一归档器**

~~~python
# RunManager._write_report，在 _write_html_report 成功返回后
try:
    NativeReportArchive(self.report_dir).archive_test_report(
        html_filename=f"{stem}.html", run=run,
    )
except (NativeReportArchiveError, OSError) as exc:
    LOGGER.warning("原生测试报告归档失败：run=%s error=%s", run.id, exc)

# AcceptanceReportWriter.write，在 HTML 和 assets manifest 写完后
try:
    NativeReportArchive(self.report_dir).archive_acceptance_report(
        html_filename=html_filename, plan=plan,
    )
except (NativeReportArchiveError, OSError) as exc:
    LOGGER.warning("原生验收报告归档失败：plan=%s error=%s", plan.plan_id, exc)
~~~

在 _write_trajectory 对每个已验证 CachedMapAsset 调用新的 freeze_map_png，原子写入 T-<attempt>_<asset-id>.map.png，并在 trajectory JSON 内加入 frozen_maps 列表（map_id、filename、受控地图元数据）。归档失败不可回滚或隐藏已有效的 HTML/CSV/assets 报告，也不可把 native 依赖注入现有 HTML/SVG 渲染逻辑。

~~~python
def freeze_map_png(asset: CachedMapAsset, target: Path, *, maximum_bytes: int) -> dict:
    width, height, pixels = _read_pgm(Path(asset.cache_image))
    if (width, height) != (asset.width, asset.height) or width * height > 16_000_000:
        raise TrajectoryRenderError(f"地图尺寸发生变化：{asset.label}")
    body = _png_gray(width, height, pixels)
    if len(body) > maximum_bytes:
        raise TrajectoryRenderError(f"地图冻结图超过大小限制：{asset.label}")
    _atomic_write_bytes(target, body)
    return {"map_id": asset.id, "filename": target.name}
~~~

- [ ] **Step 4: 回归 producer 和现有报告行为**

Run: pixi run pytest tests/test_offline_modules.py -k 'report or trajectory' tests/test_acceptance.py -k 'report or archive' -q

Expected: PASS，包括既有 HTML 内嵌 SVG 和验收 manifest 行为。

- [ ] **Step 5: 提交 producer 集成**

~~~bash
git add autodrive_console/run_manager.py autodrive_console/acceptance_report.py tests/test_offline_modules.py tests/test_acceptance.py
git commit -m "feat: archive new mobile report data"
~~~

### Task 4: 暴露只读 API、兼容索引、异步回填和删除联动

**Files:**
- Modify: web_console.py:1-120、441-500、1677-1694、1893-1925
- Modify: tests/test_offline_modules.py
- Modify: tests/test_acceptance.py

**Consumes:** Tasks 1–3 的 NativeReportArchive。

**Produces:** reports 索引的可选 native_report、四个 native 只读端点、非阻塞历史回填和 filename 删除后的 sidecar/PNG 清理。

- [ ] **Step 1: 写出失败的 HTTP、兼容和回填测试**

~~~python
def test_reports_index_keeps_existing_fields_and_adds_only_valid_native_summary(tmp_path):
    _write_html_report_fixture(tmp_path, "报告_20260928_100001_测试_123456789abc.html")
    _archive_fixture(tmp_path)
    with patch.object(web_console, "WORKSPACE", tmp_path):
        record = web_console.ConsoleHandler._reports()[0]

    assert {"filename", "size", "modified_at", "csv_filename", "report_type", "title"} <= set(record)
    assert record["native_report"]["schema_version"] == 1

def test_native_routes_return_contract_data_png_and_safe_errors(tmp_path, http_client):
    report_id, trajectory_id = _archive_fixture_and_start_console(tmp_path, http_client)
    assert http_client.get(f"/api/reports/{report_id}/native?limit=1").status == 200
    image = http_client.get(f"/api/reports/{report_id}/native/trajectories/{trajectory_id}/map.png")
    assert image.headers["Content-Type"] == "image/png"
    assert http_client.get("/api/reports/../native").status == 400
    assert http_client.get("/api/reports/rpt_missing/native").status == 404

def test_historic_backfill_is_worker_owned_and_delete_removes_native_payload(tmp_path):
    _write_historic_report_and_structured_trajectory(tmp_path)
    archive = NativeReportArchive(tmp_path / "reports")
    assert archive.summary_for_filename(_HISTORIC_NAME) is None
    _run_one_backfill_batch(archive)
    assert archive.summary_for_filename(_HISTORIC_NAME) is not None
    with patch.object(web_console, "WORKSPACE", tmp_path):
        web_console.ConsoleHandler._delete_report(_HISTORIC_NAME)
    assert archive.summary_for_filename(_HISTORIC_NAME) is None
~~~

- [ ] **Step 2: 运行失败测试**

Run: pixi run pytest tests/test_offline_modules.py -k 'native_routes or reports_index or historic_backfill' tests/test_acceptance.py -k native -q

Expected: FAIL，因为 ConsoleHandler 还没有 native 路由、worker 和索引增量。

- [ ] **Step 3: 以精确路由顺序实现 HTTP 和 worker**

~~~python
elif path.startswith("/api/reports/") and "/native" in path:
    self._native_report_route(path, parse_qs(request.query, keep_blank_values=True))
~~~

定义 _native_report_archive()，每次从当前 WORKSPACE/reports 构建归档器，使现有以 patch WORKSPACE 的 Backend 测试继续有效；worker 启动时获得自己的同一工作区实例。_native_report_route 先以完整路径正则拆段，再对每个 report_id/trajectory_id 调用 token 校验，因此畸形 native URL 固定为 400 而不是落入静态 404。仅在 ThreadingHTTPServer 已监听后启动单 daemon 回填线程；每轮固定少量报告，调用 archive_historic_report 后通过 stop event 短暂等待。禁止从 GET 调用该 worker。严格拒绝重复 cursor/limit、samples 缺 cursor、非十进制 limit 与超范围 limit。_reports 保留原排序、200 项上限和全部 Existing 字段，仅在完整 sidecar 时添加 native_report。_delete_report 在既有 HTML/CSV/manifest/trajectory 删除成功后，调用 _native_report_archive().delete_for_filename(target.name)，且保持幂等。

- [ ] **Step 4: 运行 HTTP 与完整 Backend 验证**

Run: pixi run pytest tests/test_native_report_archive.py tests/test_offline_modules.py tests/test_acceptance.py -q

Expected: PASS。

Run: ./scripts/test-backend.sh

Expected: PASS。

- [ ] **Step 5: 提交 HTTP 和迁移实现**

~~~bash
git add web_console.py tests/test_offline_modules.py tests/test_acceptance.py
git commit -m "feat: serve native mobile reports"
~~~

### Task 5: 验证消费者、发布契约并完成运维说明

**Files:**
- Modify: shared/contracts/task_execution.md:83-195
- Modify: docs/backend/README.md
- Test: mobile/test/features/reports/data/reports_repository_test.dart
- Test: mobile/test/features/reports/application/native_report_detail_controller_test.dart
- Test: mobile/test/features/reports/application/native_report_trajectory_controller_test.dart

**Consumes:** Task 4 的真实 Backend payload 和现有 Flutter ReportsRepository/report controllers。

**Produces:** 已验证的 Existing 契约，以及定义 sidecar 所有权、回填和删除行为的运维说明。

- [ ] **Step 1: 运行既有 Mobile 消费者检查**

Run: cd mobile && fvm flutter analyze && fvm flutter test -r expanded test/features/reports/data/reports_repository_test.dart test/features/reports/application/native_report_detail_controller_test.dart test/features/reports/application/native_report_trajectory_controller_test.dart

Expected: PASS；既有测试必须证明缺失 native_report、畸形 native payload、opaque 请求构造、详情/样本分页与 404 都不会回退为 HTML/CSV。

- [ ] **Step 2: 运行 PC Web 回归检查**

Run: ./scripts/test-web.sh

Expected: PASS；确认 autodrive_console/web/reports.js 仍只读取 Existing 索引字段并用 filename 删除。

- [ ] **Step 3: 仅在证据完整时升级契约并写清运维边界**

~~~markdown
### Mobile Native Reports

**Status: Existing**
**Runtime producer:** robot_backend (autodrive_console.native_report_archive.NativeReportArchive)
**Consumers:** mobile native report repository/controllers; **PC Web:** non-consumer.
**Verified:** ./scripts/test-backend.sh; ./scripts/test-web.sh; cd mobile && fvm flutter analyze && fvm flutter test -r expanded
~~~

在 docs/backend/README.md 说明 .native-reports/ 是 Backend 管理的报告证据：新报告自动写入、历史报告逐步回填、不得手工编辑，并只能随既有 filename 删除接口一起清理。

- [ ] **Step 4: 最终跨模块验证**

Run: ./scripts/test-backend.sh && ./scripts/test-web.sh && (cd mobile && fvm flutter analyze && fvm flutter test -r expanded)

Expected: 全部 PASS。若 FVM 不存在，记录精确缺失的可执行文件并保持契约 Planned，不得把未验证的 API 宣布为 Existing。

- [ ] **Step 5: 提交契约与运维文档**

~~~bash
git add shared/contracts/task_execution.md docs/backend/README.md
git commit -m "docs: publish native report API contract"
~~~

## Final Review Checklist

- [ ] 每个 native GET 响应均来自完整 sidecar，且不包含 filename/path/URL/HTML/CSV/SVG/raw ROS。
- [ ] 畸形 report/trajectory/cursor/limit 为 400；格式合法但无权、缺失、跨报告或已删除资源为 404。
- [ ] 删除只接受 filename，且只在 legacy 删除成功后清理对应 backend-owned sidecar/PNG。
- [ ] 回填异步、受限、不会由请求处理器触发。
- [ ] 新测试和验收报告均产生 schema v1 sidecar；PC HTML/CSV 流程没有改动。
- [ ] Backend、Web、Mobile 三组验证均通过后才把 shared 契约标记 Existing。
