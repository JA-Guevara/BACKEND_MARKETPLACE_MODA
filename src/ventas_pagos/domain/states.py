"""Commerce state transitions, independent of HTTP and persistence."""
TRANSITIONS = {"paid": {"processing"}, "processing": {"shipped"}, "shipped": {"delivered"}}
