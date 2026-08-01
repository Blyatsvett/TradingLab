# US Labor Day Event Study — Research Charter

## Project purpose

This project tests whether economically exposed US securities exhibit repeatable abnormal returns around US Labor Day.

The study is independent of all prior event studies. Generic analytical infrastructure may be reused, but hypotheses, candidate securities, selected event windows, benchmark choices, exclusions, portfolio construction rules, validation decisions and forward-test files must originate within this project.

## Core research question

Do economically exposed US securities exhibit abnormal returns around Labor Day that are distinguishable from:

* generic pre-holiday effects;
* September equity-market seasonality;
* month-turn effects;
* macroeconomic announcements;
* company earnings;
* summer travel seasonality;
* back-to-school spending;
* commodity-price movements;
* severe weather and hurricanes?

## Mechanism-first requirement

Candidate securities may only enter the research universe when supported by a documented economic mechanism.

Strong holiday activity by itself is not sufficient. Each hypothesis must explain why the operational effect could lead to a recurring return pattern, delayed information incorporation, recurring investor attention, temporary order flow or a post-event reversal.

## Primary hypothesis families

### H1 — Gasoline and refining

Labor Day is a major road-travel weekend and occurs near the end of the US summer driving season.

The hypothesis tests for:

* pre-holiday gasoline-demand anticipation;
* effects on refiners and fuel retailers;
* a possible post-holiday end-of-season reversal.

### H2 — Automotive dealers

Labor Day promotions may concentrate vehicle transactions and outgoing model-year inventory clearance.

The primary focus is dealership economics. Automobile manufacturers must be tested separately because incentives may improve volume while reducing margins.

### H3 — Domestic leisure travel

The three-day weekend may concentrate domestic airline, hotel, booking-platform, cruise, casino and attraction demand.

A return effect must be distinguished from general summer travel seasonality and weather-related disruptions.

### H0 — Generic pre-holiday effect

The broad market may experience recurring pre-holiday sentiment, liquidity or order-flow effects.

This is a control hypothesis and must not be interpreted as evidence for any Labor Day industry mechanism.

## Event definition

US Labor Day is the first Monday in September.

The NYSE is closed on the holiday.

Event time is defined using actual NYSE trading sessions:

* `S-1`: final trading session before Labor Day;
* `S+1`: first trading session after Labor Day;
* event time zero is prohibited because Labor Day is not a trading session.

## Samples

* Discovery: 1998–2014
* Validation: 2015–2025
* Forward test: 2026 onward

Validation may not be used to repeatedly redesign a discovery result.

## Discovery rules

Discovery may evaluate the preregistered event windows in `config/event_windows.yaml`.

At most one primary daily window may be selected per hypothesis family.

Selection must consider:

* economic plausibility;
* mean and median abnormal return;
* directional consistency;
* bootstrap uncertainty;
* leave-one-year-out stability;
* subperiod stability;
* placebo ranking;
* benchmark consistency;
* transaction costs;
* MAE and MFE;
* implementation risk.

The largest historical return is not, by itself, a valid selection criterion.

## Validation rules

Before validation is inspected, each tested hypothesis must have frozen:

* securities;
* direction;
* event window;
* benchmark model;
* contamination treatment;
* portfolio construction;
* transaction-cost assumptions;
* rejection criteria.

No substitutions may be made after validation inspection.

## Contamination policy

Every result must be shown in at least two forms:

1. **All-in executable sample** — includes every trade that the strategy would actually have taken.
2. **Clean attribution sample** — applies predefined contamination rules.

Observations may not be removed merely because their returns are unusually positive or negative.

Contamination categories include:

* Employment Situation;
* CPI and PPI;
* ISM Manufacturing and Services;
* JOLTS;
* GDP and major BEA releases;
* FOMC decisions, minutes and significant Federal Reserve events;
* company earnings and material corporate announcements;
* crude-oil and gasoline shocks;
* refinery outages;
* hurricanes and major weather disruptions;
* month-turn effects;
* other US market holidays;
* crisis regimes.

Every exclusion or flag must be recorded at the security-year level with a reason.

## Benchmark hierarchy

Primary models:

1. Market-adjusted return
2. Estimated market model
3. Sector-adjusted return
4. Market-and-sector model

Robustness models may include factor, commodity and industry-specific controls.

## Placebo policy

Placebos must include:

* shifted dates around Labor Day;
* calendar-matched September periods;
* other three-day Monday holidays;
* matched macro-announcement status where feasible.

## Portfolio policy

The primary portfolio is equal-weighted within each hypothesis family.

Return-optimized portfolio weights are prohibited.

Externally measured economic-exposure weights may be reported as a secondary specification when the measurements were defined without using event returns.

Long-only and beta-hedged implementations must be reported separately.

## Forward-test policy

The final forward specification must be frozen before the first eligible entry date.

The lock must contain:

* configuration files;
* candidate securities;
* selected windows;
* portfolio rules;
* cost assumptions;
* data cut-off;
* code version;
* file hashes;
* creation timestamp.

The forward result must be reported even when contaminated, unsuccessful or operationally inconvenient.
