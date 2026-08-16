"""Divergence scoring and arbitrage detection (Phase 2).

See :mod:`arbitrium.divergence.engine`. Four independent axes are reported and
never blended: belief disagreement (``divergence``), capturable edge
(``net_edge_after_spread``), economic size (``expected_value_at_depth``), and
risk-free arbitrage (``detect_arbitrage``).
"""
