//! Unit catalog for Convert mode.
//!
//! Each unit converts through its category's base unit:
//! base = value × factor + offset (temperature), or factor ÷ value for the
//! reciprocal fuel-economy units. Currency units are built from the rates
//! Exodus's `/api/calculator/rates` route returns (units per US dollar).

use crate::dec::Dec;

pub const CATEGORIES: [&str; 15] = [
    "Angle", "Area", "Currency", "Data", "Energy", "Force", "Fuel", "Length",
    "Power", "Pressure", "Speed", "Temperature", "Time", "Volume", "Weight",
];

#[derive(Clone, Debug)]
pub struct Unit {
    pub id: String,
    pub category: &'static str,
    pub name: &'static str,
    pub abbr: String,
    pub factor: f64,
    pub offset: f64,
    pub reciprocal: bool,
}

struct Row(&'static str, &'static str, &'static str, &'static str, f64, f64, bool);

#[allow(clippy::too_many_arguments)]
const fn u(category: &'static str, key: &'static str, name: &'static str, abbr: &'static str, factor: f64, offset: f64, reciprocal: bool) -> Row {
    Row(category, key, name, abbr, factor, offset, reciprocal)
}

/// Bases: degree, m², byte, joule, newton, L/100 km, metre, watt, pascal, m/s, kelvin, second, litre, kilogram.
const TABLE: &[Row] = &[
    u("Angle", "deg", "Degrees", "deg", 1.0, 0.0, false),
    u("Angle", "rad", "Radians", "rad", 180.0 / std::f64::consts::PI, 0.0, false),
    u("Angle", "grad", "Gradians", "grad", 0.9, 0.0, false),
    u("Angle", "rev", "Revolutions", "rev", 360.0, 0.0, false),
    u("Angle", "arcmin", "Arc Minutes", "arcmin", 1.0 / 60.0, 0.0, false),
    u("Angle", "arcsec", "Arc Seconds", "arcsec", 1.0 / 3600.0, 0.0, false),
    u("Area", "km2", "Square Kilometers", "km²", 1e6, 0.0, false),
    u("Area", "ha", "Hectares", "ha", 1e4, 0.0, false),
    u("Area", "m2", "Square Meters", "m²", 1.0, 0.0, false),
    u("Area", "cm2", "Square Centimeters", "cm²", 1e-4, 0.0, false),
    u("Area", "mm2", "Square Millimeters", "mm²", 1e-6, 0.0, false),
    u("Area", "mi2", "Square Miles", "mi²", 2589988.110336, 0.0, false),
    u("Area", "ac", "Acres", "ac", 4046.8564224, 0.0, false),
    u("Area", "yd2", "Square Yards", "yd²", 0.83612736, 0.0, false),
    u("Area", "ft2", "Square Feet", "ft²", 0.09290304, 0.0, false),
    u("Area", "in2", "Square Inches", "in²", 0.00064516, 0.0, false),
    u("Data", "bit", "Bits", "bit", 0.125, 0.0, false),
    u("Data", "B", "Bytes", "B", 1.0, 0.0, false),
    u("Data", "kbit", "Kilobits", "kbit", 125.0, 0.0, false),
    u("Data", "KB", "Kilobytes", "KB", 1e3, 0.0, false),
    u("Data", "KiB", "Kibibytes", "KiB", 1024.0, 0.0, false),
    u("Data", "Mbit", "Megabits", "Mbit", 125000.0, 0.0, false),
    u("Data", "MB", "Megabytes", "MB", 1e6, 0.0, false),
    u("Data", "MiB", "Mebibytes", "MiB", 1048576.0, 0.0, false),
    u("Data", "Gbit", "Gigabits", "Gbit", 1.25e8, 0.0, false),
    u("Data", "GB", "Gigabytes", "GB", 1e9, 0.0, false),
    u("Data", "GiB", "Gibibytes", "GiB", 1073741824.0, 0.0, false),
    u("Data", "TB", "Terabytes", "TB", 1e12, 0.0, false),
    u("Data", "TiB", "Tebibytes", "TiB", 1099511627776.0, 0.0, false),
    u("Data", "PB", "Petabytes", "PB", 1e15, 0.0, false),
    u("Energy", "J", "Joules", "J", 1.0, 0.0, false),
    u("Energy", "kJ", "Kilojoules", "kJ", 1e3, 0.0, false),
    u("Energy", "cal", "Calories", "cal", 4.184, 0.0, false),
    u("Energy", "kcal", "Kilocalories", "kcal", 4184.0, 0.0, false),
    u("Energy", "Wh", "Watt-Hours", "Wh", 3600.0, 0.0, false),
    u("Energy", "kWh", "Kilowatt-Hours", "kWh", 3.6e6, 0.0, false),
    u("Energy", "BTU", "British Thermal Units", "BTU", 1055.05585262, 0.0, false),
    u("Energy", "eV", "Electronvolts", "eV", 1.602176634e-19, 0.0, false),
    u("Force", "N", "Newtons", "N", 1.0, 0.0, false),
    u("Force", "kN", "Kilonewtons", "kN", 1e3, 0.0, false),
    u("Force", "dyn", "Dynes", "dyn", 1e-5, 0.0, false),
    u("Force", "lbf", "Pound-Force", "lbf", 4.4482216152605, 0.0, false),
    u("Force", "kgf", "Kilogram-Force", "kgf", 9.80665, 0.0, false),
    u("Fuel", "l100km", "Liters per 100 Kilometers", "L/100km", 1.0, 0.0, false),
    u("Fuel", "kml", "Kilometers per Liter", "km/L", 100.0, 0.0, true),
    u("Fuel", "mpg", "Miles per Gallon", "mpg", 235.214583, 0.0, true),
    u("Fuel", "mpgimp", "Miles per Imperial Gallon", "mpg (imp)", 282.480936, 0.0, true),
    u("Length", "km", "Kilometers", "km", 1e3, 0.0, false),
    u("Length", "m", "Meters", "m", 1.0, 0.0, false),
    u("Length", "cm", "Centimeters", "cm", 1e-2, 0.0, false),
    u("Length", "mm", "Millimeters", "mm", 1e-3, 0.0, false),
    u("Length", "um", "Micrometers", "µm", 1e-6, 0.0, false),
    u("Length", "nm", "Nanometers", "nm", 1e-9, 0.0, false),
    u("Length", "mi", "Miles", "mi", 1609.344, 0.0, false),
    u("Length", "yd", "Yards", "yd", 0.9144, 0.0, false),
    u("Length", "ft", "Feet", "ft", 0.3048, 0.0, false),
    u("Length", "in", "Inches", "in", 0.0254, 0.0, false),
    u("Length", "nmi", "Nautical Miles", "NM", 1852.0, 0.0, false),
    u("Length", "ly", "Light-Years", "ly", 9.4607304725808e15, 0.0, false),
    u("Power", "mW", "Milliwatts", "mW", 1e-3, 0.0, false),
    u("Power", "W", "Watts", "W", 1.0, 0.0, false),
    u("Power", "kW", "Kilowatts", "kW", 1e3, 0.0, false),
    u("Power", "MW", "Megawatts", "MW", 1e6, 0.0, false),
    u("Power", "hp", "Horsepower", "hp", 745.69987158227, 0.0, false),
    u("Pressure", "Pa", "Pascals", "Pa", 1.0, 0.0, false),
    u("Pressure", "hPa", "Hectopascals", "hPa", 100.0, 0.0, false),
    u("Pressure", "kPa", "Kilopascals", "kPa", 1e3, 0.0, false),
    u("Pressure", "bar", "Bars", "bar", 1e5, 0.0, false),
    u("Pressure", "mbar", "Millibars", "mbar", 100.0, 0.0, false),
    u("Pressure", "atm", "Atmospheres", "atm", 101325.0, 0.0, false),
    u("Pressure", "psi", "Pounds per Square Inch", "psi", 6894.757293168, 0.0, false),
    u("Pressure", "inHg", "Inches of Mercury", "inHg", 3386.389, 0.0, false),
    u("Pressure", "mmHg", "Millimeters of Mercury", "mmHg", 133.322387415, 0.0, false),
    u("Speed", "mps", "Meters per Second", "m/s", 1.0, 0.0, false),
    u("Speed", "kmh", "Kilometers per Hour", "km/h", 1.0 / 3.6, 0.0, false),
    u("Speed", "mph", "Miles per Hour", "mph", 0.44704, 0.0, false),
    u("Speed", "fps", "Feet per Second", "ft/s", 0.3048, 0.0, false),
    u("Speed", "kn", "Knots", "kn", 1852.0 / 3600.0, 0.0, false),
    u("Temperature", "C", "Celsius", "°C", 1.0, 273.15, false),
    u("Temperature", "F", "Fahrenheit", "°F", 5.0 / 9.0, 273.15 - 32.0 * 5.0 / 9.0, false),
    u("Temperature", "K", "Kelvin", "K", 1.0, 0.0, false),
    u("Time", "ns", "Nanoseconds", "ns", 1e-9, 0.0, false),
    u("Time", "us", "Microseconds", "µs", 1e-6, 0.0, false),
    u("Time", "ms", "Milliseconds", "ms", 1e-3, 0.0, false),
    u("Time", "s", "Seconds", "s", 1.0, 0.0, false),
    u("Time", "min", "Minutes", "min", 60.0, 0.0, false),
    u("Time", "h", "Hours", "h", 3600.0, 0.0, false),
    u("Time", "d", "Days", "d", 86400.0, 0.0, false),
    u("Time", "wk", "Weeks", "wk", 604800.0, 0.0, false),
    u("Time", "yr", "Years", "yr", 31557600.0, 0.0, false),
    u("Volume", "m3", "Cubic Meters", "m³", 1e3, 0.0, false),
    u("Volume", "L", "Liters", "L", 1.0, 0.0, false),
    u("Volume", "mL", "Milliliters", "mL", 1e-3, 0.0, false),
    u("Volume", "cm3", "Cubic Centimeters", "cm³", 1e-3, 0.0, false),
    u("Volume", "gal", "Gallons", "gal", 3.785411784, 0.0, false),
    u("Volume", "galimp", "Imperial Gallons", "gal (imp)", 4.54609, 0.0, false),
    u("Volume", "qt", "Quarts", "qt", 0.946352946, 0.0, false),
    u("Volume", "pt", "Pints", "pt", 0.473176473, 0.0, false),
    u("Volume", "cup", "Cups", "cup", 0.2365882365, 0.0, false),
    u("Volume", "floz", "Fluid Ounces", "fl oz", 0.0295735295625, 0.0, false),
    u("Volume", "tbsp", "Tablespoons", "tbsp", 0.01478676478125, 0.0, false),
    u("Volume", "tsp", "Teaspoons", "tsp", 0.00492892159375, 0.0, false),
    u("Volume", "ft3", "Cubic Feet", "ft³", 28.316846592, 0.0, false),
    u("Volume", "in3", "Cubic Inches", "in³", 0.016387064, 0.0, false),
    u("Weight", "t", "Metric Tons", "t", 1e3, 0.0, false),
    u("Weight", "kg", "Kilograms", "kg", 1.0, 0.0, false),
    u("Weight", "g", "Grams", "g", 1e-3, 0.0, false),
    u("Weight", "mg", "Milligrams", "mg", 1e-6, 0.0, false),
    u("Weight", "lb", "Pounds", "lb", 0.45359237, 0.0, false),
    u("Weight", "oz", "Ounces", "oz", 0.028349523125, 0.0, false),
    u("Weight", "st", "Stones", "st", 6.35029318, 0.0, false),
    u("Weight", "ton", "Short Tons", "ton", 907.18474, 0.0, false),];

pub fn units() -> Vec<Unit> {
    TABLE
        .iter()
        .map(|r| Unit {
            id: format!("{}.{}", r.0.to_lowercase(), r.1),
            category: r.0,
            name: r.2,
            abbr: r.3.to_string(),
            factor: r.4,
            offset: r.5,
            reciprocal: r.6,
        })
        .collect()
}

/// Looks up a static unit, or a currency unit (`currency.EUR`) from the rates.
pub fn find(id: &str, rates: &[(String, f64)]) -> Option<Unit> {
    if let Some(code) = id.strip_prefix("currency.") {
        let per_usd = rates.iter().find(|(c, _)| c == code)?.1;
        if per_usd <= 0.0 {
            return None;
        }
        return Some(Unit {
            id: id.to_string(),
            category: "Currency",
            name: "",
            abbr: code.to_string(),
            factor: 1.0 / per_usd,
            offset: 0.0,
            reciprocal: false,
        });
    }
    units().into_iter().find(|u| u.id == id)
}

fn to_base(u: &Unit, v: f64) -> f64 {
    if u.reciprocal {
        if v == 0.0 { f64::INFINITY } else { u.factor / v }
    } else {
        v * u.factor + u.offset
    }
}

fn from_base(u: &Unit, v: f64) -> f64 {
    if u.reciprocal {
        if v == 0.0 { f64::INFINITY } else { u.factor / v }
    } else {
        (v - u.offset) / u.factor
    }
}

/// Converts between two units of one category; None when impossible.
pub fn convert(value: &Dec, from: &Unit, to: &Unit) -> Option<Dec> {
    if from.category != to.category {
        return None;
    }
    if from.id == to.id {
        return Some(value.clone());
    }
    Dec::from_f64(from_base(to, to_base(from, value.to_f64())))
}
