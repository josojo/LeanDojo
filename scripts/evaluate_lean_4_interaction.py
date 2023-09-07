
import ray
import random
import json
import argparse
from tqdm import tqdm
from loguru import logger

from lean_dojo import *
from lean_dojo.constants import TACTIC_MEMORY_LIMIT
from lean_dojo.utils import ray_actor_pool, working_directory


def read_next_response(proc):
    while True:
        line = proc.stdout.readline().strip()
        # logger.info(line)
        if line == "":
            raise EOFError
        try:
            return json.loads(line)
        except json.decoder.JSONDecodeError:
            continue


def _validate_ground_truth(thm) -> bool:
    logger.info(thm)
    theorem = thm["theorem"]
    proof = thm["proof"]

    # Validate using LeanDojo.
    lean_dojo_result = None

    try:
        with Dojo(theorem, 1000) as (dojo, init_state):
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

    # repo = LeanGitRepo("https://github.com/leanprover-community/mathlib4", "5a919533f110b7d76410134a237ee374f24eaaad")
    repo = LeanGitRepo("https://github.com/yangky11/lean4-example", "7d711f6da4584ecb7d4f057715e1f72ba175c910")
    traced_repo = trace(repo)

    theorems = {}

    logger.info("Loading the theorems")
    logger.info("number of theorems in repo", traced_repo.get_traced_theorems())

    for t in tqdm(traced_repo.get_traced_theorems()):

        if t.is_private == 'True':  # Discard private theorems.
            continue

        if t.repo.url == 'https://github.com/leanprover/lean4':
            # this repo is not yet supported to be parsed
            continue

        proof = t.get_single_tactic_proof()
        print(t)
        print("proof is ",  proof)
        if proof is None:  # Discard theorems without tactic-style proofs.
            continue

        # namespaces = list(set(inside + opened))
        print(t.theorem.full_name)
        assert t.theorem.full_name not in theorems
        theorems[t.theorem.full_name] = {
            "theorem": t.theorem,
            "proof": proof,
            # "namespaces": namespaces,
        }

    theorems = list(theorems.values())
    random.shuffle(theorems)
    num_theorems = len(theorems)
    logger.info(f"Evaluating {num_theorems} theorems")

    # for thm in theorems:
    #    _validate_ground_truth(thm)
    # return

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
