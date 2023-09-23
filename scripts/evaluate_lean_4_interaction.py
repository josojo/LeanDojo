import argparse
import random
import ray
from tqdm import tqdm
from loguru import logger
from typing import List

from lean_dojo import *
from lean_dojo.constants import NUM_WORKERS, TACTIC_MEMORY_LIMIT
from lean_dojo.utils import ray_actor_pool, working_directory

# aereraaaaakk
## instfuctions for runnning this script:
# Export the following envs:
# VERBOSE=1
# CONTAINER="native" -> This is much faster than the docker container.
# install
## install the lean toolchain used in the linked repo, ie for the current matlib4 repo:
# elan toolchain install leanprover:lean4:4.0.0-mathlib-lean-3.4.2


def _validate_ground_truth(thm) -> bool:
    theorem = thm["theorem"]
    proof = thm["proof"]

    # Validate using LeanDojo.
    lean_dojo_result = None

    try:
        with Dojo(theorem, 1000) as (dojo, init_state):
            if not isinstance(init_state, TacticState):
                raise TypeError(f"Expected TacticState, got {type(init_state).__name__}")
            logger.debug(f"Initial state: {init_state}")
            logger.debug("starting run_tac")
            res = dojo.run_tac(init_state, proof)
            logger.debug("finished run_tac")
            if isinstance(res, ProofFinished):
                lean_dojo_result = True
            else:
                logger.error(f"LeanDojo error (proof not finished): {res}")
                logger.debug(f"For the following theorem:\n{thm['theorem']}")
                logger.debug(f"For the following proof:\n{thm['proof']}")
                lean_dojo_result = False
    except Exception as ex:
        logger.error(f"LeanDojo error: {ex}")
        lean_dojo_result = False

    logger.debug(f"Result for thm:{theorem} is {lean_dojo_result}")
    if lean_dojo_result == False:
        logger.debug(f"Proof for thm:{theorem} is {proof}")
    return lean_dojo_result


@ray.remote
class RayHelper:
    def validate_ground_truth(self, thm) -> bool:
        return _validate_ground_truth(thm)


def main() -> None:
    """Main function."""
    parser = argparse.ArgumentParser()
    args = parser.parse_args()
    logger.info(args)

    os.environ["TACTIC_TIMEOUT"] = "600000"

    repo = LeanGitRepo(
        "https://github.com/yangky11/lean4-example",
        "7d711f6da4584ecb7d4f057715e1f72ba175c910",
    )
    repo = LeanGitRepo(
        "https://github.com/leanprover-community/mathlib4",
        "355541ae7a2455222f179dcf7f074aa2c45eb8aa",
    )
    # mathlib_file_to_parse = "Mathlib/Data/Set/Finite.trace.xml"
    mathlib_file_to_parse = "Mathlib/Tactic/NormNum/Prime.trace.xml"
    mathlib_thereom_in_file_to_parse = "Mathlib.Meta.NormNum.minFacHelper_1"

    traced_repo = trace(repo, None, mathlib_file_to_parse)
    theorems = {}

    logger.info("Loading the theorems")
    logger.info("number of theorems in repo", len(traced_repo.get_traced_theorems()))

    for t in tqdm(traced_repo.get_traced_theorems()):
        if t.is_private == "True":  # Discard private theorems.
            continue

        # if t.repo.url == 'https://github.com/leanprover/lean4':
        #     # this repo is not yet supported to be parsed
        #     continue
        # we re only interested in theorems from the repo we are looking at
        if t.repo.url != repo.url:
            continue

        proof = t.get_proof()
        if t.has_tactic_proof() is False:
            proof = "exact (" + proof + ")"
        else:
            assert proof.startswith("by")
            proof = proof[len("by") :].strip()

        if proof is None:  # Discard theorems without tactic-style proofs.
            logger.warning(f"Discarding {t.theorem.full_name} without tactic-style proof")
            continue

        if proof.startswith("exact (|"):
            # Currently, we do not support multiple proofs for a theorem
            continue

        assert t.theorem.full_name not in theorems
        if (
            mathlib_thereom_in_file_to_parse != None
            and not mathlib_thereom_in_file_to_parse == t.theorem.full_name
        ):
            continue
        theorems[t.theorem.full_name] = {
            "theorem": t.theorem,
            "proof": proof,
        }

    logger.info(f"Loaded {len(theorems)} theorems")

    theorems = list(theorems.values())
    random.shuffle(theorems)
    num_theorems = len(theorems)
    logger.info(f"Evaluating {num_theorems} theorems")

    num_lean_dojo_correct = 0
    if NUM_WORKERS <= 1:
        for thm in theorems:
            print(thm)
            num_lean_dojo_correct += _validate_ground_truth(thm)
    else:
        with ray_actor_pool(RayHelper) as pool:
            results = list(
                tqdm(
                    pool.map_unordered(
                        lambda a, thm: a.validate_ground_truth.remote(thm), theorems
                    ),
                    total=len(theorems),
                )
            )
            for x in results:
                num_lean_dojo_correct += x

    logger.info(f"LeanDojo: {num_lean_dojo_correct}/{num_theorems}")


if __name__ == "__main__":
    main()
