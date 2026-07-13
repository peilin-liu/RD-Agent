"""
Model workflow with session control
"""

import asyncio
import os

import fire

from rdagent.app.qlib_rd_loop.conf import MODEL_PROP_SETTING
from rdagent.components.workflow.rd_loop import RDLoop
from rdagent.core.exception import ModelEmptyError
from rdagent.core.region_config import get_default_region
from rdagent.log import rdagent_logger as logger


class ModelRDLoop(RDLoop):
    skip_loop_error = (ModelEmptyError,)


def main(
    path=None,
    step_n: int | None = None,
    loop_n: int | None = None,
    all_duration: str | None = None,
    checkout: bool = True,
    base_features_path: str | None = None,
    region: str | None = None,
    market: str | None = None,
    **kwargs,
):
    """
    Auto R&D Evolving loop for fintech models
    """
    resolved_region = region or get_default_region()
    os.environ["QLIB_REGION"] = resolved_region
    os.environ["QLIB_MARKET"] = market or ""
    logger.info(
        f"[task start] scenario=fin_model region={resolved_region} market={market or '(region default)'}"
    )
    logger.log_object({"region": resolved_region, "market": market or ""}, tag="task.meta")

    if path is None:
        model_loop = ModelRDLoop(MODEL_PROP_SETTING)
    else:
        model_loop = ModelRDLoop.load(path, checkout=checkout)
    model_loop._init_base_features(base_features_path)
    if "user_interaction_queues" in kwargs and kwargs["user_interaction_queues"] is not None:
        model_loop._set_interactor(*kwargs["user_interaction_queues"])
        model_loop._interact_init_params()
    asyncio.run(model_loop.run(step_n=step_n, loop_n=loop_n, all_duration=all_duration))


if __name__ == "__main__":
    fire.Fire(main)
