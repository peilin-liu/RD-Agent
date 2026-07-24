## ADDED Requirements

### Requirement: Workspace artifact enumeration
The system SHALL scan a workspace directory for mlruns artifacts and return an ordered list of artifact files. The scan SHALL traverse `<workspace_path>/mlruns/<experiment_id>/<recorder_id>/artifacts/` recursively, including nested subdirectories (e.g., `portfolio_analysis/`, `sig_analysis/`). Each returned entry SHALL include the relative path (from `artifacts/`), absolute path, and file size in bytes.

#### Scenario: Workspace with successful run artifacts
- **WHEN** a workspace at `<workspace_path>` contains `mlruns/439742684322255683/3cabfd9bf64b48029506fa880f1ebff7/artifacts/params.pkl` and `mlruns/439742684322255683/3cabfd9bf64b48029506fa880f1ebff7/artifacts/portfolio_analysis/report_normal_1day.pkl`
- **THEN** the scan SHALL return at least two entries: one with relative path `params.pkl` and one with relative path `portfolio_analysis/report_normal_1day.pkl`, each with its absolute path and file size.

#### Scenario: Workspace without mlruns
- **WHEN** a workspace at `<workspace_path>` has no `mlruns/` subdirectory (e.g., a factor-only workspace that did not run `qrun`)
- **THEN** the scan SHALL return an empty list, and the caller SHALL treat this as "no artifacts to display", not an error.

#### Scenario: Workspace with multiple experiments under mlruns
- **WHEN** a workspace has `mlruns/<exp_A>/<rec_A>/artifacts/` and `mlruns/<exp_B>/<rec_B>/artifacts/` (e.g., multiple loops each created a new MLflow experiment)
- **THEN** the scan SHALL aggregate artifacts from ALL experiment/recorder directories, with the relative path prefixed by `<experiment_id>/<recorder_id>/` so the user can distinguish which loop produced which file.

### Requirement: Artifact display in workspace Files popover
The UI SHALL render an "Model Artifacts" subsection inside the existing Files popover of `workspace_win` (`rdagent/log/ui/ds_trace.py`). The subsection SHALL appear ONLY when the artifact enumeration for that workspace returns a non-empty list. Each artifact SHALL be rendered as a `st.download_button` labeled `<relative_path> (<human_readable_size>)`. The subsection SHALL NOT alter the existing `.py`/`.md` file display logic above it.

#### Scenario: Workspace with artifacts
- **WHEN** the user opens the Files popover for a workspace whose `mlruns/.../artifacts/` contains `params.pkl` (18 KB) and `pred.pkl` (676 KB)
- **THEN** the UI SHALL render, below the existing code file tabs, a "Model Artifacts" header and two download buttons labeled `params.pkl (18 KB)` and `pred.pkl (676 KB)`, each producing the file bytes when clicked.

#### Scenario: Workspace without artifacts
- **WHEN** the user opens the Files popover for a workspace with no `mlruns/` subdirectory
- **THEN** the UI SHALL NOT render the "Model Artifacts" header or any download buttons; the popover shows only the existing `.py`/`.md` files.

### Requirement: Artifact download produces correct bytes
The download button for an artifact SHALL deliver byte-identical content to the file on disk. The bytes SHALL be read fresh from the artifact's absolute path at click time (not cached from a prior scan), so that files modified between scan and click are reflected.

#### Scenario: Download params.pkl
- **WHEN** the user clicks the download button for `params.pkl` whose absolute path is `.../artifacts/params.pkl`
- **THEN** the browser SHALL receive a file whose bytes match `open(.../artifacts/params.pkl, 'rb').read()` exactly, with download filename `params.pkl`.

#### Scenario: Artifact file deleted between scan and click
- **WHEN** an artifact file is deleted from disk after the scan ran but before the user clicks download
- **THEN** the UI SHALL show an inline error message "File no longer exists: <path>" instead of crashing, and the rest of the popover SHALL remain functional.

### Requirement: Optional bulk download as zip
The UI SHALL provide a secondary "Download all as zip" button inside the "Model Artifacts" subsection. Clicking it SHALL produce a zip archive containing all artifacts with their relative paths preserved. The zip SHALL be built in-memory and streamed to the browser. This button SHALL appear only when there are 2 or more artifacts.

#### Scenario: Bulk download with multiple artifacts
- **WHEN** the workspace has 3 artifact files under `artifacts/` and the user clicks "Download all as zip"
- **THEN** the browser SHALL receive a zip archive containing all 3 files with their relative paths (including subdirectory prefixes like `portfolio_analysis/report_normal_1day.pkl`) preserved.

#### Scenario: Single artifact no zip button
- **WHEN** the workspace has exactly 1 artifact file
- **THEN** the UI SHALL NOT render the "Download all as zip" button (the single per-file download button suffices).

### Requirement: Large artifact handling
The system SHALL cap in-memory download MB. For artifacts larger than 50 MB, the per-file download button SHALL be disabled and labeled `<relative_path> (<size>) — too large for in-browser download, access via filesystem: <absolute_path>`. The "Download all as zip" button SHALL also be disabled if any included artifact exceeds 50 MB.

#### Scenario: Artifact within size cap
- **WHEN** an artifact file is 9 MB (`indicators_normal_1day_obj.pkl`)
- **THEN** its download button SHALL be enabled and functional.

#### Scenario: Artifact exceeding size cap
- **WHEN** an artifact file is 120 MB
- **THEN** its download button SHALL be disabled, labeled with the filesystem path hint, and the "Download all as zip" button (if present) SHALL also be disabled.
