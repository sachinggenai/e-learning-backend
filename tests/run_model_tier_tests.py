"""Tests for US-BKND-AI-044 - Two-Tier Model Architecture."""
from app.services.ai.model_tier_router import ModelTierRouter, ModelTier, DEFAULT_TIER_MODELS

passed = 0; failed = 0; failures = []
def check(n, c, d=""):
    global passed, failed
    if c: passed += 1; print(f"  PASS: {n}")
    else: failed += 1; failures.append((n, d)); print(f"  FAIL: {n} -- {d}")

def main():
    global passed, failed
    router = ModelTierRouter()

    print("=== Task Classification ===")
    check("list pages -> planner", router.classify_task(tool_name="list_pages") == ModelTier.PLANNER)
    check("fetch page -> planner", router.classify_task(tool_name="fetch_page") == ModelTier.PLANNER)
    check("propose_create -> generator", router.classify_task(tool_name="propose_create_page") == ModelTier.GENERATOR)
    check("propose_update -> generator", router.classify_task(tool_name="propose_update_page") == ModelTier.GENERATOR)
    check("propose_delete -> generator", router.classify_task(tool_name="propose_delete_page") == ModelTier.GENERATOR)
    check("generate_course -> generator", router.classify_task(tool_name="generate_course") == ModelTier.GENERATOR)

    print("\n=== Message-Based Classification ===")
    check("create page message -> generator", router.classify_task(user_message="create a new welcome page") == ModelTier.GENERATOR)
    check("list pages message -> planner", router.classify_task(user_message="show me all pages") == ModelTier.PLANNER)
    check("write assessment -> generator", router.classify_task(user_message="write a quiz for chapter 3") == ModelTier.GENERATOR)
    check("help message -> planner", router.classify_task(user_message="how many pages do I have?") == ModelTier.PLANNER)
    check("empty message -> planner", router.classify_task(user_message="") == ModelTier.PLANNER)

    print("\n=== Model Resolution ===")
    check("planner model is haiku", router.get_model_for_tier(ModelTier.PLANNER) == "claude-haiku-4-20250514")
    check("generator model is sonnet", router.get_model_for_tier(ModelTier.GENERATOR) == "claude-sonnet-4-20250514")
    model = router.get_model_for_task(tool_name="propose_create_page")
    check("get_model_for_task returns sonnet", model == "claude-sonnet-4-20250514")

    print("\n=== Cost Savings ===")
    r0 = ModelTierRouter()
    check("no requests = 0 savings pct", r0.estimate_cost_savings()["savings_pct"] == 0)

    # Simulate routing with fresh router
    r3 = ModelTierRouter()
    for _ in range(7): r3.classify_task(tool_name="list_pages")
    for _ in range(3): r3.classify_task(tool_name="propose_create_page")
    savings = r3.estimate_cost_savings()
    check("planner count", savings["planner_requests"] == 7)
    check("generator count", savings["generator_requests"] == 3)
    check("savings > 0", savings["savings_pct"] > 0)
    check("actual < hypothetical", savings["actual_cost_usd"] < savings["hypothetical_cost_all_generator_usd"])

    print("\n=== Stats ===")
    stats = router.get_stats()
    check("has routing_counts", "routing_counts" in stats)
    check("has cost_estimate", "cost_estimate" in stats)

    print("\n=== Custom Models ===")
    r2 = ModelTierRouter(planner_model="custom-haiku", generator_model="custom-opus")
    check("custom planner", r2.get_model_for_tier(ModelTier.PLANNER) == "custom-haiku")
    check("custom generator", r2.get_model_for_tier(ModelTier.GENERATOR) == "custom-opus")

    print("\n=== Default Tier Models ===")
    check("default planner haiku", "haiku" in DEFAULT_TIER_MODELS["planner"])
    check("default generator sonnet", "sonnet" in DEFAULT_TIER_MODELS["generator"])

    print(f"\n{'='*60}")
    print(f"RESULTS: {passed} passed, {failed} failed")
    return failed == 0

if __name__ == "__main__":
    exit(0 if main() else 1)
