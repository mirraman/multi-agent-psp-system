import os
import uuid
from datetime import datetime, timezone
from app.agents.BaseAgent import ActionMessageHandlerBehaviour, BaseAgent, AgentMessage
from spade.behaviour import PeriodicBehaviour
import json

from app.utils.db import (
    DatabaseConnection,
    upsert_protein_result,
    upsert_riboswitch_result,
    claim_pending_job,
    complete_task,
    fail_task,
    insert_job_log,
)


class CoordinatorAgent(BaseAgent):
    def __init__(self, jid: str, password: str):
        super().__init__(jid, password)

        self.jobs = {}
        self.db_job_mapping = {}

        self.data_agent_jid = self.format_jid("data_agent")
        self.psp_agent_jid = self.format_jid("psp_agent")
        self.processing_agent_jid = self.format_jid("processing_agent")
        self.synthesis_agent_jid = self.format_jid("synthesis_agent")
        self.pocket_agent_jid = self.format_jid("pocket_agent")
        self.output_agent_jid = self.format_jid("output_agent")
        self.analysis_agent_jid = self.format_jid("analysis_agent")
        self.modal_agent_jid = self.format_jid("modal_agent")
        self.riboswitch_agent_jid = self.format_jid("riboswitch_agent")

    async def _log(self, job: dict, message: str, level: str = "info"):
        """Write a log entry for a job (to DB and stdout)."""
        print(f"[{job.get('db_job_id', '?')}] {message}")
        db_job_id = job.get("db_job_id")
        if db_job_id and DatabaseConnection.engine is not None:
            await insert_job_log(db_job_id, message, level)

    async def start_job(self, input_type: str, input_value: str, db_job_id: str = None, options: dict = None):
        job_id = db_job_id or str(uuid.uuid4())

        self.jobs[job_id] = {
            "status": "fetching_data",
            "input_type": input_type,
            "input_value": input_value,
            "options": options or {},
            "raw_data": None,
            "psp_results": None,
            "processing_results": None,
            "analysis_results": None,
            "synthesis_results": None,
            "pocket_results": None,
            "output_results": None,
            "db_job_id": db_job_id,
        }

        await self._log(self.jobs[job_id], f"Job started — input_type={input_type}, value={input_value[:60]}")

        if input_type == "riboswitch":
            self.jobs[job_id]["status"] = "designing_riboswitch"
            try:
                ga_params = json.loads(input_value)
            except Exception:
                ga_params = {}
            msg = self.create_message(
                to=self.riboswitch_agent_jid,
                msg_type="request",
                action="design_riboswitch",
                payload=ga_params,
                job_id=job_id,
            )
        else:
            msg = self.create_message(
                to=self.data_agent_jid,
                msg_type="request",
                action="fetch_data",
                payload={"input_type": input_type, "input_value": input_value},
                job_id=job_id,
            )
        await self.send(msg)
        return job_id

    async def setup(self):
        behaviour = ActionMessageHandlerBehaviour(
            self,
            action_to_handler={},
            default_handler="handle_response",
        )
        self.add_behaviour(behaviour)

        check_db_behaviour = CheckDatabaseForJobsBehaviour(period=5)
        self.add_behaviour(check_db_behaviour)

        print(f"CoordinatorAgent {self.jid} started")

    async def handle_response(self, agent_msg: AgentMessage):
        job_id = agent_msg.job_id
        action = agent_msg.action

        job = self.jobs.get(job_id)
        if not job:
            print(f"Job {job_id} not found in memory — ignoring message action={action}")
            return

        if action == "data_fetched":
            job["raw_data"] = agent_msg.payload.get("data")
            raw_data = job.get("raw_data") or {}

            # Disease flow: resolve disease -> ranked targets, then continue pipeline
            # with the top actionable UniProt accession.
            if job.get("input_type") == "disease":
                if raw_data.get("error"):
                    error_msg = f"Disease lookup failed: {raw_data['error']}"
                    job["status"] = "failed"
                    await self._log(job, error_msg, level="error")
                    db_job_id = job.get("db_job_id")
                    if DatabaseConnection.engine is not None and db_job_id:
                        try:
                            await fail_task(db_job_id, error_message=error_msg)
                        except Exception as e:
                            print(f"Failed to mark task failed: {e}")
                    return

                disease_context = raw_data.get("disease_context") or {}
                targets = disease_context.get("targets", [])
                if not targets:
                    error_msg = "Disease lookup returned no actionable targets"
                    job["status"] = "failed"
                    await self._log(job, error_msg, level="error")
                    db_job_id = job.get("db_job_id")
                    if DatabaseConnection.engine is not None and db_job_id:
                        try:
                            await fail_task(db_job_id, error_message=error_msg)
                        except Exception as e:
                            print(f"Failed to mark task failed: {e}")
                    return

                selected_target = targets[0]
                selected_accession = selected_target.get("accession")
                if not selected_accession:
                    error_msg = "Top disease target did not include a UniProt accession"
                    job["status"] = "failed"
                    await self._log(job, error_msg, level="error")
                    db_job_id = job.get("db_job_id")
                    if DatabaseConnection.engine is not None and db_job_id:
                        try:
                            await fail_task(db_job_id, error_message=error_msg)
                        except Exception as e:
                            print(f"Failed to mark task failed: {e}")
                    return

                job["disease_context"] = disease_context
                job["selected_target"] = selected_target
                await self._log(
                    job,
                    "Disease resolved to target "
                    f"{selected_target.get('gene_symbol', '?')} ({selected_accession}), "
                    f"score={selected_target.get('association_score', 'n/a')}. "
                    "Continuing with standard protein pipeline."
                )

                # Switch the in-memory flow to a normal accession job and fetch
                # canonical UniProt/PDB payload for the selected target.
                job["input_type"] = "accession"
                job["input_value"] = selected_accession
                job["status"] = "fetching_data"
                msg = self.create_message(
                    to=self.data_agent_jid,
                    msg_type="request",
                    action="fetch_data",
                    payload={"input_type": "accession", "input_value": selected_accession},
                    job_id=job_id,
                )
                await self.send(msg)
                return

            job["status"] = "predicting_structure"
            sequence = raw_data.get("uniprot", {}).get("sequence", "")
            if not sequence:
                error_msg = "No sequence available after data fetch"
                job["status"] = "failed"
                await self._log(job, error_msg, level="error")
                db_job_id = job.get("db_job_id")
                if DatabaseConnection.engine is not None and db_job_id:
                    try:
                        await fail_task(db_job_id, error_message=error_msg)
                    except Exception as e:
                        print(f"Failed to mark task failed: {e}")
                return
            await self._log(job, f"Data fetched. Sequence length={len(sequence)}. Routing to structure predictor.")

            try:
                modal_threshold = int(os.getenv("MODAL_MIN_SEQUENCE_LENGTH", "400"))
            except ValueError:
                modal_threshold = 400
            use_modal = os.getenv("ENABLE_MODAL", "0") == "1"
            await self._log(
                job,
                (
                    f"Routing decision: seq_len={len(sequence)}, "
                    f"ENABLE_MODAL={'1' if use_modal else '0'}, "
                    f"MODAL_MIN_SEQUENCE_LENGTH={modal_threshold}"
                ),
            )

            if len(sequence) > modal_threshold and use_modal:
                await self._log(
                    job,
                    f"Sequence > {modal_threshold}aa — routing to Modal/ColabFold (ENABLE_MODAL=1)",
                )
                msg = self.create_message(
                    to=self.modal_agent_jid,
                    msg_type="request",
                    action="predict_colabfold_modal",
                    payload={"sequence": sequence},
                    job_id=job_id,
                )
            else:
                if len(sequence) > modal_threshold:
                    await self._log(
                        job,
                        (
                            f"Sequence > {modal_threshold}aa but ENABLE_MODAL!=1 "
                            "— routing to ESMFold fallback"
                        ),
                        level="warning",
                    )
                else:
                    await self._log(job, f"Sequence <= {modal_threshold}aa — routing to ESMFold")
                msg = self.create_message(
                    to=self.psp_agent_jid,
                    msg_type="request",
                    action="predict_structure",
                    payload={"sequence": sequence},
                    job_id=job_id,
                )
            await self.send(msg)

        elif action == "structure_predicted":
            job["psp_results"] = agent_msg.payload.get("results", {}) or {}
            job["models_used"] = agent_msg.payload.get("models_used", [])
            job["psp_errors"] = agent_msg.payload.get("errors", {})
            job["status"] = "processing"

            raw_data = job.get("raw_data") or {}
            af = raw_data.get("alphafold_db") or {}
            if isinstance(af, dict) and af.get("pdb"):
                job["psp_results"]["alphafold_db"] = {
                    "pdb": af["pdb"],
                    "source": af.get("source", "AlphaFold DB (EBI)"),
                    "mean_plddt": af.get("mean_plddt"),
                }
                mu = list(job["models_used"] or [])
                if "alphafold_db" not in mu:
                    mu.append("alphafold_db")
                    job["models_used"] = mu
            exp = raw_data.get("experimental_best_pdb") or {}
            if isinstance(exp, dict) and exp.get("pdb_text"):
                job["psp_results"]["experimental"] = {
                    "pdb": exp["pdb_text"],
                    "pdb_id": exp.get("pdb_id"),
                    "resolution": exp.get("resolution"),
                    "source": "Experimental PDB",
                }
                mu = list(job["models_used"] or [])
                if "experimental" not in mu:
                    mu.append("experimental")
                    job["models_used"] = mu

            # Modal fallback: if long-sequence ColabFold path failed to produce
            # any model, retry once through ESMFold instead of hanging/aborting.
            if not job["models_used"] and not job.get("esmfold_fallback_attempted"):
                modal_error = (job["psp_errors"] or {}).get("colabfold_modal")
                if modal_error:
                    sequence = (job.get("raw_data") or {}).get("uniprot", {}).get("sequence", "")
                    if sequence:
                        job["esmfold_fallback_attempted"] = True
                        job["status"] = "predicting_structure"
                        await self._log(
                            job,
                            "Modal/ColabFold unavailable. Falling back to ESMFold for this job.",
                            level="warning",
                        )
                        msg = self.create_message(
                            to=self.psp_agent_jid,
                            msg_type="request",
                            action="predict_structure",
                            payload={"sequence": sequence},
                            job_id=job_id,
                        )
                        await self.send(msg)
                        return

            models_str = ", ".join(job["models_used"]) if job["models_used"] else "none"
            await self._log(job, f"Structure predicted. Models used: {models_str}")
            if job["psp_errors"]:
                await self._log(job, f"Some models failed: {list(job['psp_errors'].keys())}", level="warning")

            msg = self.create_message(
                to=self.processing_agent_jid,
                msg_type="request",
                action="process",
                payload={
                    "raw_data": job["raw_data"],
                    "psp_results": job["psp_results"],
                },
                job_id=job_id,
            )
            await self.send(msg)

        elif action == "processed":
            job["processing_results"] = agent_msg.payload.get("metrics")
            job["status"] = "analyzing"
            await self._log(job, "Processing complete. Dispatching analysis.")
            msg = self.create_message(
                to=self.analysis_agent_jid,
                msg_type="request",
                action="analyze",
                payload={
                    "raw_data": job["raw_data"],
                    "psp_results": job["psp_results"],
                    "processing_results": job["processing_results"],
                },
                job_id=job_id,
            )
            await self.send(msg)

        elif action == "analyzed":
            job["analysis_results"] = agent_msg.payload.get("analysis")
            job["status"] = "synthesizing"
            summary = (job["analysis_results"] or {}).get("summary", "")
            await self._log(job, f"Analysis complete. {summary}")
            msg = self.create_message(
                to=self.synthesis_agent_jid,
                msg_type="request",
                action="synthesize",
                payload={
                    "raw_data": job["raw_data"],
                    "psp_results": job["psp_results"],
                    "processing_results": job["processing_results"],
                    "analysis_results": job["analysis_results"],
                },
                job_id=job_id,
            )
            await self.send(msg)

        elif action == "synthesized":
            job["synthesis_results"] = agent_msg.payload.get("synthesis")
            job["status"] = "detecting_pockets"

            best_model = job["synthesis_results"].get("best_model", "esmfold")
            psp_results = job.get("psp_results", {})
            model_payload = {
                "esmfold": psp_results.get("esmfold", {}).get("pdb", ""),
                "colabfold_modal": psp_results.get("colabfold_modal", {}).get("pdb", ""),
                "alphafold_db": psp_results.get("alphafold_db", {}).get("pdb", ""),
                "experimental": psp_results.get("experimental", {}).get("pdb", ""),
            }

            proc = job.get("processing_results") or {}
            plddt_per_residue = proc.get("plddt_per_residue", {})
            fallback_plddt = proc.get("esmfold_plddt_mean")
            if not isinstance(fallback_plddt, (int, float)):
                fallback_plddt = proc.get("alphafold_db_plddt_mean")
            await self._log(job, f"Synthesis complete. Best model: {best_model}. Running pocket detection.")

            msg = self.create_message(
                to=self.pocket_agent_jid,
                msg_type="request",
                action="detect_pockets",
                payload={
                    "models": model_payload,
                    "best_model": best_model,
                    "plddt_per_residue": plddt_per_residue,
                    "fallback_plddt_mean": fallback_plddt,
                    "best_model_source": job["synthesis_results"].get("best_model_source", best_model),
                },
                job_id=job_id,
            )
            await self.send(msg)

        elif action == "pockets_detected":
            job["pocket_results"] = agent_msg.payload
            job["status"] = "generating_output"
            pocket_count = agent_msg.payload.get("pocket_summary", {}).get("high_confidence", 0)
            await self._log(job, f"Pocket detection done. {pocket_count} high-confidence pockets. Generating output.")

            accession = job["input_value"] if job["input_type"] == "accession" else job_id
            msg = self.create_message(
                to=self.output_agent_jid,
                msg_type="request",
                action="generate_output",
                payload={
                    "accession": accession,
                    "raw_data": job["raw_data"],
                    "psp_results": job["psp_results"],
                    "processing_results": job["processing_results"],
                    "synthesis_results": job["synthesis_results"],
                    "analysis_results": job["analysis_results"],
                    "pocket_results": job["pocket_results"],
                },
                job_id=job_id,
            )
            await self.send(msg)

        elif action == "output_generated":
            job["output_results"] = agent_msg.payload.get("output_path")
            job["status"] = "completed"
            await self._log(job, f"Pipeline complete. Output: {job['output_results']}")

            db_job_id = job.get("db_job_id")
            if DatabaseConnection.engine is not None and db_job_id:
                try:
                    await complete_task(db_job_id, output_path=job["output_results"])
                except Exception as e:
                    print(f"Failed to mark task complete: {e}")

                final_output = {
                    "accession": job["input_value"],
                    "task_id": int(db_job_id) if db_job_id else None,
                    "status": "completed",
                    "timestamp": datetime.now(timezone.utc),
                    "output_path": job["output_results"],
                    "metrics": job.get("processing_results"),
                    "synthesis": job.get("synthesis_results"),
                    "uniprot": job["raw_data"].get("uniprot"),
                    "psp_results": job.get("psp_results"),
                    "models_used": job.get("models_used", []),
                    "psp_errors": job.get("psp_errors", {}),
                    "analysis": job.get("analysis_results"),
                    "pockets": job.get("pocket_results"),
                }
                try:
                    await upsert_protein_result(job["input_value"], final_output)
                    print(f"Saved final results to DB for {job['input_value']}")
                except Exception as e:
                    print(f"Failed to save protein result: {e}")

        elif action == "riboswitch_designed":
            job["status"] = "completed"
            result = agent_msg.payload
            await self._log(job, "Riboswitch design complete.")

            db_job_id = job.get("db_job_id")
            if DatabaseConnection.engine is not None and db_job_id:
                try:
                    await complete_task(db_job_id)
                except Exception as e:
                    print(f"Failed to mark task complete: {e}")
                try:
                    await upsert_riboswitch_result(int(db_job_id), result)
                    print(f"Saved riboswitch result to DB for job {db_job_id}")
                except Exception as e:
                    print(f"Failed to save riboswitch result: {e}")

        elif action == "error":
            error_msg = agent_msg.payload.get("error", "Unknown error")
            job["status"] = "failed"
            await self._log(job, f"Pipeline error: {error_msg}", level="error")

            db_job_id = job.get("db_job_id")
            if DatabaseConnection.engine is not None and db_job_id:
                try:
                    await fail_task(db_job_id, error_message=error_msg)
                except Exception as e:
                    print(f"Failed to mark task failed: {e}")


class CheckDatabaseForJobsBehaviour(PeriodicBehaviour):
    async def run(self):
        if DatabaseConnection.engine is None:
            return

        try:
            pending_job = await claim_pending_job()
        except Exception as e:
            print(f"DB poll error: {e}")
            return

        if pending_job:
            accession = pending_job.get("input_value")
            input_type = pending_job.get("input_type", "accession")
            db_job_id = str(pending_job["id"])
            print(f"Coordinator: Picked up job {db_job_id} for {str(accession)[:60]} ({input_type})")

            await self.agent.start_job(
                input_type=input_type,
                input_value=accession,
                db_job_id=db_job_id,
            )