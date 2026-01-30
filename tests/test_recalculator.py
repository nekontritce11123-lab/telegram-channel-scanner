"""
Unit тесты для recalculate_trust_from_breakdown() из scanner/recalculator.py.

Тестирует пересчёт trust_factor из сохранённых trust_details и llm_analysis.

Покрывает:
- Пустые и отсутствующие данные
- Одиночные и множественные penalties
- LLM trust factor
- Комбинированные сценарии
- Floor at 0.1
- Невалидные данные
"""
import pytest
from scanner.recalculator import recalculate_trust_from_breakdown


class TestRecalculateTrustFromBreakdown:
    """Тесты для функции recalculate_trust_from_breakdown()."""

    def test_recalculate_trust_empty_breakdown(self):
        """Empty breakdown returns 1.0."""
        result = recalculate_trust_from_breakdown({})
        assert result == 1.0

    def test_recalculate_trust_no_penalties(self):
        """No multipliers returns 1.0."""
        breakdown = {
            'trust_details': {
                'spam_posting': {'posts_per_day': 5.0},  # No multiplier key
                'other_metric': {'value': 0.5}  # No multiplier key
            }
        }
        result = recalculate_trust_from_breakdown(breakdown)
        assert result == 1.0

    def test_recalculate_trust_single_penalty(self):
        """One penalty applied correctly."""
        breakdown = {
            'trust_details': {
                'ghost_channel': {'multiplier': 0.5, 'online_ratio': 0.05}
            }
        }
        result = recalculate_trust_from_breakdown(breakdown)
        assert result == 0.5

    def test_recalculate_trust_multiple_penalties(self):
        """Multiple penalties multiplied together."""
        breakdown = {
            'trust_details': {
                'spam_posting': {'multiplier': 0.75},
                'hollow_views': {'multiplier': 0.6}
            }
        }
        # Expected: 0.75 * 0.6 = 0.45
        result = recalculate_trust_from_breakdown(breakdown)
        assert result == 0.45

    def test_recalculate_trust_with_llm_factor(self):
        """LLM trust factor applied correctly."""
        breakdown = {'trust_details': {}}
        llm_analysis = {'llm_trust_factor': 0.8}

        result = recalculate_trust_from_breakdown(breakdown, llm_analysis)
        assert result == 0.8

    def test_recalculate_trust_combined(self):
        """trust_details + llm_analysis combined correctly."""
        # Based on @elooop example
        breakdown = {
            'trust_details': {
                'spam_posting': {'multiplier': 0.75, 'posts_per_day': 16.6}
            }
        }
        llm_analysis = {'llm_trust_factor': 0.99}

        # Expected: 0.75 * 0.99 = 0.7425 -> rounded to 0.74
        result = recalculate_trust_from_breakdown(breakdown, llm_analysis)
        assert result == 0.74

    def test_recalculate_trust_floor_at_01(self):
        """Result never below 0.1."""
        breakdown = {
            'trust_details': {
                'penalty1': {'multiplier': 0.1},
                'penalty2': {'multiplier': 0.1}
            }
        }
        # Expected: max(0.1, 0.01) = 0.1
        result = recalculate_trust_from_breakdown(breakdown)
        assert result == 0.1

    def test_recalculate_trust_ignores_invalid(self):
        """Ignores non-dict or missing multiplier entries."""
        breakdown = {
            'trust_details': {
                'valid_penalty': {'multiplier': 0.8},
                'invalid_string': 'not a dict',
                'invalid_none': None,
                'missing_multiplier': {'value': 0.5},
                'invalid_multiplier_type': {'multiplier': 'not a number'},
            }
        }
        # Only valid_penalty (0.8) should be applied
        result = recalculate_trust_from_breakdown(breakdown)
        assert result == 0.8

    # -------------------------------------------------------------------------
    # Edge cases
    # -------------------------------------------------------------------------

    def test_recalculate_trust_multiplier_equals_1_ignored(self):
        """Multiplier = 1.0 is not a penalty and should be ignored."""
        breakdown = {
            'trust_details': {
                'no_penalty': {'multiplier': 1.0}
            }
        }
        result = recalculate_trust_from_breakdown(breakdown)
        assert result == 1.0

    def test_recalculate_trust_multiplier_greater_than_1_ignored(self):
        """Multiplier > 1.0 should be ignored (only penalties matter)."""
        breakdown = {
            'trust_details': {
                'bonus': {'multiplier': 1.2},  # Should be ignored
                'penalty': {'multiplier': 0.9}
            }
        }
        result = recalculate_trust_from_breakdown(breakdown)
        assert result == 0.9

    def test_recalculate_trust_llm_factor_equals_1_ignored(self):
        """LLM trust factor = 1.0 is not a penalty."""
        breakdown = {'trust_details': {}}
        llm_analysis = {'llm_trust_factor': 1.0}

        result = recalculate_trust_from_breakdown(breakdown, llm_analysis)
        assert result == 1.0

    def test_recalculate_trust_missing_trust_details(self):
        """Breakdown without trust_details key returns 1.0."""
        breakdown = {
            'cv_views': {'value': 0.3, 'points': 5},
            'reach': {'value': 0.6, 'points': 8}
        }
        result = recalculate_trust_from_breakdown(breakdown)
        assert result == 1.0

    def test_recalculate_trust_none_llm_analysis(self):
        """None llm_analysis handled correctly."""
        breakdown = {
            'trust_details': {
                'penalty': {'multiplier': 0.7}
            }
        }
        result = recalculate_trust_from_breakdown(breakdown, None)
        assert result == 0.7

    def test_recalculate_trust_empty_llm_analysis(self):
        """Empty llm_analysis dict handled correctly."""
        breakdown = {
            'trust_details': {
                'penalty': {'multiplier': 0.7}
            }
        }
        result = recalculate_trust_from_breakdown(breakdown, {})
        assert result == 0.7

    def test_recalculate_trust_llm_missing_factor_key(self):
        """LLM analysis without llm_trust_factor key."""
        breakdown = {'trust_details': {}}
        llm_analysis = {'tier': 'A', 'llm_bonus': 5}  # No llm_trust_factor

        result = recalculate_trust_from_breakdown(breakdown, llm_analysis)
        assert result == 1.0

    def test_recalculate_trust_real_world_scenario(self):
        """Real-world scenario with multiple trust penalties."""
        # Simulating a channel with spam posting + bot wall detection
        breakdown = {
            'trust_details': {
                'spam_posting': {'multiplier': 0.75, 'posts_per_day': 16.6},
                'bot_wall': {'multiplier': 0.6, 'decay_range': (0.98, 1.02)},
                'hollow_views': {'multiplier': 0.6, 'views_members_ratio': 5.0}
            }
        }
        llm_analysis = {'llm_trust_factor': 0.95}

        # Expected: 0.75 * 0.6 * 0.6 * 0.95 = 0.2565 -> 0.26
        result = recalculate_trust_from_breakdown(breakdown, llm_analysis)
        assert result == 0.26

    def test_recalculate_trust_extreme_penalties_floor(self):
        """Extreme penalties still floor at 0.1."""
        breakdown = {
            'trust_details': {
                'id_clustering_fatality': {'multiplier': 0.0},  # FATALITY
            }
        }
        # Even with 0.0 multiplier, floor is 0.1
        result = recalculate_trust_from_breakdown(breakdown)
        assert result == 0.1

    def test_recalculate_trust_rounding(self):
        """Verify rounding to 2 decimal places."""
        breakdown = {
            'trust_details': {
                'penalty1': {'multiplier': 0.77},
                'penalty2': {'multiplier': 0.83}
            }
        }
        # 0.77 * 0.83 = 0.6391 -> rounds to 0.64
        result = recalculate_trust_from_breakdown(breakdown)
        assert result == 0.64

    def test_recalculate_trust_zero_llm_factor(self):
        """LLM trust factor of 0.0 is falsy and gets ignored (returns 1.0).

        Note: The implementation uses `if llm_trust and ...` which makes 0.0 falsy.
        This is intentional - a 0.0 factor would be unusual and is treated as "no data".
        """
        breakdown = {'trust_details': {}}
        llm_analysis = {'llm_trust_factor': 0.0}

        result = recalculate_trust_from_breakdown(breakdown, llm_analysis)
        assert result == 1.0  # 0.0 is falsy, so no penalty applied

    def test_recalculate_trust_integer_multiplier(self):
        """Integer multiplier values handled correctly."""
        breakdown = {
            'trust_details': {
                'penalty': {'multiplier': 0}  # Integer 0
            }
        }
        result = recalculate_trust_from_breakdown(breakdown)
        assert result == 0.1  # Floor
