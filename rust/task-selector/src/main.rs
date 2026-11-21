use orca_task_selector::{select, Candidate};
use std::io::{self, Read};

fn main() {
    let limit = std::env::args()
        .nth(1)
        .and_then(|value| value.parse::<usize>().ok())
        .unwrap_or(0);

    let mut input = String::new();
    if io::stdin().read_to_string(&mut input).is_err() {
        eprintln!("invalid input");
        std::process::exit(2);
    }

    let mut candidates = Vec::new();
    for line in input.lines() {
        let fields: Vec<&str> = line.split('\t').collect();
        if fields.len() != 4 {
            eprintln!("invalid candidate row");
            std::process::exit(2);
        }
        let priority_score = match fields[1].parse::<i64>() {
            Ok(value) => value,
            Err(_) => { eprintln!("invalid score"); std::process::exit(2); }
        };
        let catalog_order = match fields[2].parse::<usize>() {
            Ok(value) => value,
            Err(_) => { eprintln!("invalid catalog order"); std::process::exit(2); }
        };
        let eligible = match fields[3] {
            "true" => true,
            "false" => false,
            _ => { eprintln!("invalid eligibility flag"); std::process::exit(2); }
        };
        candidates.push(Candidate {
            id: fields[0].to_owned(),
            priority_score,
            catalog_order,
            eligible,
        });
    }

    match select(&candidates, limit) {
        Ok(ids) => for id in ids { println!("{id}"); },
        Err(_) => {
            eprintln!("selection blocked");
            std::process::exit(2);
        }
    }
}
