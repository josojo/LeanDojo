from pickletools import read_uint1
import ray
import random
import json
import argparse
from tqdm import tqdm
from loguru import logger
from typing import List

from lean_dojo import *
from lean_dojo.constants import TACTIC_MEMORY_LIMIT
from lean_dojo.utils import ray_actor_pool, working_directory

## instructions for runnning this script:
# Export the following envs:
# VERBOSE=1
# CONTAINER="native" -> This is much faster than the docker container.
# install 
## install the lean toolchain used in the linked repo, ie for the current matlib4 repo:
# elan toolchain install leanprover:lean4:4.0.0-mathlib-lean-3.4.2


def _validate_ground_truth(thm) -> bool:
    logger.info(thm)
    theorem = thm["theorem"]
    proof = thm["proof"]

    # Validate using LeanDojo.
    lean_dojo_result = None

    try:
        with Dojo(theorem, 1000) as (dojo, init_state):
            if not isinstance(init_state, TacticState):
                raise TypeError(
                    f"Expected TacticState, got {type(init_state).__name__}"
                )
            assert init_state.num_goals == 1
            init_ctx = [decl.ident for decl in init_state.goals[0].assumptions]

            res = dojo.run_tac(init_state, proof)
            if isinstance(res, ProofFinished):
                lean_dojo_result = True
            else:
                logger.error(f"LeanDojo error: {res}")
                lean_dojo_result = False
    except Exception as ex:
        logger.error(f"LeanDojo error: {ex}")
        lean_dojo_result = False

    return lean_dojo_result

@ray.remote
class RayHelper:
    def validate_ground_truth(self, thm) -> bool:
        return _validate_ground_truth(thm)


def main() -> None:
    parser = argparse.ArgumentParser()
    args = parser.parse_args()
    logger.info(args)

    os.environ["TACTIC_TIMEOUT"] = "600000"

    repo = LeanGitRepo("https://github.com/leanprover-community/mathlib4", "355541ae7a2455222f179dcf7f074aa2c45eb8aa")
    # repo = LeanGitRepo("https://github.com/josojo/lean4-example", "82b5f8a266b0bc7870228934560d4fc691be752d")
    # repo = LeanGitRepo(
    #     "https://github.com/yangky11/lean4-example",
    #     "7d711f6da4584ecb7d4f057715e1f72ba175c910",
    # )
    traced_repo = trace(repo)
    theorems = {}

    logger.info("Loading the theorems")
    logger.info("number of theorems in repo", len(traced_repo.get_traced_theorems()))

    for t in tqdm(traced_repo.get_traced_theorems()):

        if t.is_private == "True":  # Discard private theorems.
            continue

        print(t.repo.url)
        if t.repo.url != "https://github.com/leanprover-community/mathlib4":
            continue

        proof = t.get_proof()
        if t.has_tactic_proof() is False:
            proof = "apply (" + proof+ ")"
        else:
            assert proof.startswith("by")
            proof = proof[len("by") :].strip()
        
        print(t.theorem.full_name)
        print(t)
        print("proof is ", proof)
        if proof is None:  # Discard theorems without tactic-style proofs.
            logger.warning(f"Discarding {t.theorem.full_name} without tactic-style proof")
            continue

        assert t.theorem.full_name not in theorems
        theorems[t.theorem.full_name] = {
            "theorem": t.theorem,
            "proof": proof,
        }

    logger.info(f"Loaded {len(theorems)} theorems")

    theorems = list(theorems.values())[0:10]
    random.shuffle(theorems)
    num_theorems = len(theorems)
    logger.info(f"Evaluating {num_theorems} theorems")

    with ray_actor_pool(RayHelper) as pool:
        results = list(
            tqdm(
                pool.map_unordered(
                    lambda a, thm: a.validate_ground_truth.remote(thm), theorems
                ),
                total=len(theorems),
            )
        )
        num_lean_dojo_correct = 0
        for x in results:
            num_lean_dojo_correct += x

        logger.info(f"LeanDojo: {num_lean_dojo_correct}/{num_theorems}")


if __name__ == "__main__":
    main()


# def get_imports(traced_theorem) -> List[str]:
#     traced_file = traced_theorem.traced_file
#     return traced_file.get_direct_dependencies()


# def get_proof_with_full_names(traced_theorem) -> str:
#     traced_tactics = traced_theorem.get_traced_tactics()
#     result = ""
#     for tactic in traced_tactics:
#         annotated_tactic, provenances = tactic.get_annotated_tactic()
#         for prov in provenances:
#             full_name = prov["full_name"]
#             tactic_name = full_name.split(".")[-1]
#             annotated_tactic = annotated_tactic.replace(
#                 f"<a>{tactic_name}</a>", full_name, 1
#             )
#         result += annotated_tactic

#     return result
