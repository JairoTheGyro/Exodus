use exodus_calculator::Core;
use std::time::Instant;

fn main() {
    let keys: Vec<String> = "123456.789*987.65+12/7-0.5^3=".chars().map(|c| match c {
        '+' => r#"{"cmd":"press","key":["op","add"]}"#.into(),
        '-' => r#"{"cmd":"press","key":["op","sub"]}"#.into(),
        '*' => r#"{"cmd":"press","key":["op","mul"]}"#.into(),
        '/' => r#"{"cmd":"press","key":["op","div"]}"#.into(),
        '^' => r#"{"cmd":"press","key":["op","pow"]}"#.into(),
        '.' => r#"{"cmd":"press","key":["point"]}"#.into(),
        '=' => r#"{"cmd":"press","key":["equals"]}"#.into(),
        d => format!(r#"{{"cmd":"press","key":["digit","{}"]}}"#, d),
    }).collect();
    let n = 2000;
    let start = Instant::now();
    for _ in 0..n {
        let mut core = Core::new();
        for k in &keys { std::hint::black_box(core.command(k)); }
    }
    println!("full command: {:.1} µs/key", start.elapsed().as_secs_f64() * 1e6 / (n * keys.len()) as f64);
    let start = Instant::now();
    for _ in 0..n {
        let mut core = Core::new();
        for k in &keys { core.bench_press_only(k); }
    }
    println!("press only:   {:.1} µs/key", start.elapsed().as_secs_f64() * 1e6 / (n * keys.len()) as f64);
}
