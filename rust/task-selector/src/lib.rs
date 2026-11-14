//! Deterministic, side-effect-free task ranking for the Orca queue.
//!
//! Shadow-only in phase one: no queue/state access, approvals, leases, or workers.

use std::collections::HashSet;

/// A task that has already passed caller-side schema and policy validation.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Candidate {
    pub id: String,
    pub priority_score: i64,
    pub catalog_order: usize,
    pub eligible: bool,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum SelectionError {
    EmptyTaskId,
    InvalidTaskId(String),
    InvalidLimit,
    DuplicateTaskId(String),
}

/// Select at most limit eligible tasks.
///
/// Ordering matches Python refill: descending history score, then reviewed
/// catalog order. The function is pure and has no external side effects.
pub fn select(candidates: &[Candidate], limit: usize) -> Result<Vec<String>, SelectionError> {
    if !(1..=4).contains(&limit) {
        return Err(SelectionError::InvalidLimit);
    }
    let mut seen = HashSet::with_capacity(candidates.len());

    for candidate in candidates {
        if candidate.id.trim().is_empty() {
            return Err(SelectionError::EmptyTaskId);
        }
        let bytes = candidate.id.as_bytes();
        let valid = (3..=100).contains(&bytes.len())
            && (bytes[0].is_ascii_lowercase() || bytes[0].is_ascii_digit())
            && bytes[1..].iter().all(|b| b.is_ascii_lowercase() || b.is_ascii_digit() || *b == b'.' || *b == b'_' || *b == b'-');
        if !valid {
            return Err(SelectionError::InvalidTaskId(candidate.id.clone()));
        }
        if !seen.insert(candidate.id.as_str()) {
            return Err(SelectionError::DuplicateTaskId(candidate.id.clone()));
        }
    }

    let mut ranked: Vec<(usize, &Candidate)> = candidates
        .iter()
        .enumerate()
        .filter(|(_, candidate)| candidate.eligible)
        .collect();

    ranked.sort_by(|(left_index, left), (right_index, right)| {
        right
            .priority_score
            .cmp(&left.priority_score)
            .then_with(|| left.catalog_order.cmp(&right.catalog_order))
            .then_with(|| left_index.cmp(right_index))
    });

    Ok(ranked
        .into_iter()
        .take(limit)
        .map(|(_, candidate)| candidate.id.clone())
        .collect())
}

#[cfg(test)]
mod tests {
    use super::*;

    fn candidate(id: &str, score: i64, order: usize, eligible: bool) -> Candidate {
        Candidate {
            id: id.to_owned(),
            priority_score: score,
            catalog_order: order,
            eligible,
        }
    }

    #[test]
    fn ranks_higher_history_score_first() {
        let tasks = vec![
            candidate("task-a", 1, 0, true),
            candidate("task-b", 5, 1, true),
            candidate("task-c", 3, 2, true),
        ];
        assert_eq!(select(&tasks, 3).unwrap(), vec!["task-b", "task-c", "task-a"]);
    }

    #[test]
    fn preserves_catalog_order_for_equal_scores() {
        let tasks = vec![
            candidate("task-c", 4, 2, true),
            candidate("task-a", 4, 0, true),
            candidate("task-b", 4, 1, true),
        ];
        assert_eq!(select(&tasks, 3).unwrap(), vec!["task-a", "task-b", "task-c"]);
    }

    #[test]
    fn excludes_ineligible_candidates_before_applying_limit() {
        let tasks = vec![
            candidate("held", 100, 0, false),
            candidate("ready-a", 2, 1, true),
            candidate("ready-b", 1, 2, true),
        ];
        assert_eq!(select(&tasks, 1).unwrap(), vec!["ready-a"]);
    }

    #[test]
    fn respects_zero_and_positive_limits() {
        let tasks = vec![candidate("task-a", 2, 0, true), candidate("task-b", 1, 1, true)];
        assert!(select(&tasks, 0).unwrap().is_empty());
        assert_eq!(select(&tasks, 1).unwrap(), vec!["task-a"]);
    }

    #[test]
    fn rejects_limits_outside_python_contract() {
        let tasks = vec![candidate("task-a", 2, 0, true)];
        assert_eq!(select(&tasks, 0), Err(SelectionError::InvalidLimit));
        assert_eq!(select(&tasks, 5), Err(SelectionError::InvalidLimit));
    }

    #[test]
    fn rejects_ids_outside_python_contract() {
        for id in ["ab", "UPPER", "../x", "has space", "a".repeat(101).as_str()] {
            let tasks = vec![candidate(id, 1, 0, true)];
            assert_eq!(select(&tasks, 1), Err(SelectionError::InvalidTaskId(id.to_owned())));
        }
    }

    #[test]
    fn accepts_python_task_id_characters() {
        let tasks = vec![candidate("task.a_1-x", 1, 0, true)];
        assert_eq!(select(&tasks, 1).unwrap(), vec!["task.a_1-x"]);
    }

    #[test]
    fn rejects_duplicate_ids_fail_closed() {
        let tasks = vec![candidate("same-id", 2, 0, true), candidate("same-id", 1, 1, false)];
        assert_eq!(select(&tasks, 1), Err(SelectionError::DuplicateTaskId("same-id".to_owned())));
    }

    #[test]
    fn rejects_blank_ids_fail_closed() {
        let tasks = vec![candidate("  ", 2, 0, true)];
        assert_eq!(select(&tasks, 1), Err(SelectionError::EmptyTaskId));
    }
}
