from rdagent.core.developer import Developer
from rdagent.core.experiment import ASpecificExp, Experiment
from rdagent.oai.llm_utils import md5_hash


class CachedRunner(Developer[ASpecificExp]):
    def get_cache_key(self, exp: Experiment) -> str:
        all_tasks = []
        for based_exp in exp.based_experiments:
            all_tasks.extend(based_exp.sub_tasks)
        all_tasks.extend(exp.sub_tasks)
        task_info_list = [task.get_task_information() for task in all_tasks]
        task_info_str = "\n".join(task_info_list)

        # Include the base feature map (name -> expression) in the cache key
        # so that two experiments with the same task description but different
        # factor sets do NOT share a cached result. base_features is populated
        # by qlib scenarios (user picks factors from Alpha158 + custom in the
        # UI, see rd_loop.py:_interact_init_params -> plan["features"]). Other
        # scenarios without base_features fall back to the task-only key.
        features_str = ""
        base_features = getattr(exp, "base_features", None)
        if base_features:
            features_str = "\n".join(
                f"{name}:{expr}" for name, expr in sorted(base_features.items())
            )
        return md5_hash(task_info_str + "\n[base_features]\n" + features_str)

    def assign_cached_result(self, exp: Experiment, cached_res: Experiment) -> Experiment:
        if exp.based_experiments and exp.based_experiments[-1].result is None:
            exp.based_experiments[-1].result = cached_res.based_experiments[-1].result
        exp.result = cached_res.result
        return exp
