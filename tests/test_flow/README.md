# CodeTrace manual test flow

Everything in this folder is synthetic test data. It contains no real student,
customer, patient, or other personal information.

## Files and where to use them

| File | Upload/use it at | Expected result |
|---|---|---|
| `preprocessing_leakage_demo.ipynb` | Initial **Inspect Notebook** upload | Static finding for fitting a scaler before splitting, including cross-cell alias lineage. Do not execute this example: its `X` and `y` values are intentionally undefined. |
| `forecasting_demo.ipynb` | Initial **Inspect Notebook** upload; select **Predict future observations (forecasting)** | Potential temporal findings for a randomized split without visible chronological sorting. It is source-analysis test input, not a runnable model. |
| `execution_smoke_test.ipynb` | Initial upload, then **Experiments** | A small Python-standard-library notebook that can run in the default Docker image after associating `sample_dataset.csv`. It prints the row count and a simple feature average. |
| `sample_dataset.csv` | **Overview → Analyze CSV**, and **Experiments → Associate a dataset** when running the smoke-test notebook | Dataset profile; can also be explicitly attached to a Docker run. |
| `train_split.csv` | **Leakage & Evaluation Audit → Compare explicit train and test datasets → Training split CSV** | First half of the synthetic group-overlap example. |
| `test_split.csv` | Same overlap form, **Test split CSV** | Shares `student_id` values with `train_split.csv`; expected to report overlap when group settings below are entered. |

Use the notebook and CSV files for their specific stages; uploading a notebook
does not automatically upload or open a CSV referenced in notebook code.

## Working flow

1. **Start the API and UI.** From the repository root, start the backend with
   `uvicorn backend.app.main:app --reload`. In a second terminal, serve the UI
   with `python -m http.server 5500 --directory frontend`, then open
   `http://127.0.0.1:5500`.
2. **Inspect a notebook.** Upload one of the `.ipynb` files. Choose the research
   objective that matches the test: forecasting for `forecasting_demo.ipynb`,
   or the generalization objective for the preprocessing example. Review
   Overview, Pipeline Trace, and Leakage & Evaluation Audit. The files are
   inspected statically at this stage; code is not executed.
3. **Profile a CSV (optional).** In Overview, choose `sample_dataset.csv` and
   click **Analyze CSV**. This profiles that explicitly uploaded file; it does
   not connect it to notebook variables.
4. **Compare group overlap (optional).** In the Audit page, choose
   `train_split.csv` and `test_split.csv`, then enter:
   - Evaluation objective: **Generalize to unseen entities/groups**
   - Identifier column: leave blank
   - Group column: `student_id`

   Click **Compare splits**. The report should show overlap evidence without
   exposing the raw student IDs. Group-column meaning is explicitly supplied
   here; CodeTrace does not assume every ID column is a group.
5. **Review a repair (optional).** On the Repair Center page, inspect the
   proposed change. Approve only a supported proposal, then generate a separate
   corrected notebook. The original upload is not overwritten. The two
   analysis-only demo notebooks are not intended to execute.
6. **Run the safe execution smoke test (optional).** Upload
   `execution_smoke_test.ipynb`, go to Experiments, use **Associate a dataset**
   to upload `sample_dataset.csv`, select the attached dataset, and click
   **Start execution**. This notebook uses only the Python standard library,
   which is available in the default runner. No network access is needed.
7. **Record experiment history (optional).** In the history form, enter:
   - Dataset version: `synthetic-cohort-v1`
   - Model name: `DemoClassifier`
   - Hyperparameters: `{"max_depth": 3}`
   - Training data reference: `train_split.csv`
   - Validation data reference: optional; use `validation` if applicable
   - Test data reference: use `test_split.csv` for a test evaluation
   - Metric: `accuracy`; enter a numeric value such as `0.80`
   - Decision: choose **Selected based on this result**, **Rejected based on
     this result**, or **Final test evaluation only**, as appropriate

   Save at least two records with the same dataset version and test reference,
   marking them selected/rejected, to exercise the repeated test-selection
   warning. A single final evaluation should not trigger that warning. These
   entries are user-provided history, not metrics automatically extracted from
   the run.
8. **Verify or report (optional).** For repair verification, execute both the
   original and corrected versions and select their saved runs in Verification.
   Generate a report from Evidence Reports. A successful run by itself does not
   prove that leakage is absent.

## Docker: what it does and when it is needed

Docker is optional for static notebook inspection, CSV profiling/overlap, repair
generation, experiment-history entry, benchmarking, and report creation. It is
required only when you explicitly start a notebook execution or paired
experiment. CodeTrace sends execution to the isolated runner; it does not fall
back to running notebook code on the API host.

From the repository root, build the expected local runner image:

```powershell
docker build -t codetrace-notebook-runner:1.0.0 backend/execution
```

Then set the image name in the **same PowerShell session** that starts the API:

```powershell
$env:CODETRACE_EXECUTION_IMAGE = "codetrace-notebook-runner:1.0.0"
uvicorn backend.app.main:app --reload
```

Check Docker Desktop/Engine is running and confirm the image is present with
`docker image inspect codetrace-notebook-runner:1.0.0`. If Docker or the image is
unavailable, execution is reported unavailable; static analysis remains usable.

The runner is configured for no network, a non-root user, a read-only container
filesystem with a bounded writable temporary area, dropped Linux capabilities,
and CPU, memory, process, output, and time limits. It includes a small pinned
Python environment; it does not install arbitrary notebook packages at runtime.
For notebooks needing additional dependencies, add reviewed, exactly pinned
packages to `backend/execution/Dockerfile`, rebuild and scan the image, then use
a fixed image tag or digest. Do not enable network access or install packages
from an untrusted notebook.
