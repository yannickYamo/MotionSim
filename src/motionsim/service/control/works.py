"""The works the explorations cite, each with the mark docs/CONTROL_RESEARCH.md gives it:
read in full (`body`), or only as an abstract."""

from __future__ import annotations

GROUPS = ("losses", "dynamics", "sensing", "robustness", "thermal")

# Works docs/CONTROL_RESEARCH.md lists as opened: title, year, link, and how far it was read.
WORKS: dict[str, tuple[str, int, str, str]] = {
    "S84": (
        "Preshaping command inputs to reduce system vibration",
        1990,
        "https://doi.org/10.1115/1.2894142",
        "abstract",
    ),
    "S83": (
        "Resonant load control methods for industrial servo drives",
        2000,
        "https://doi.org/10.1109/IAS.2000.882073",
        "abstract",
    ),
    "S82": (
        "Adaptive periodic speed fluctuation suppression for permanent magnet compressor drives",
        2025,
        "https://doi.org/10.3390/s25072074",
        "abstract",
    ),
    "S81": (
        "Speed control of interior permanent magnet synchronous motor drive for the flux weakening operation",
        1997,
        "https://doi.org/10.1109/28.567075",
        "abstract",
    ),
    "S79": (
        "High-Performance Speed Control of PMSM Using Fuzzy Sliding Mode with Load Torque Observer",
        2025,
        "https://doi.org/10.3390/app15137053",
        "abstract",
    ),
    "S80": (
        "PMSM Speed Regulation Using an Inverse Hyperbolic Sine Function-Based Active Disturbance Rejection "
        "Control Strategy",
        2026,
        "https://doi.org/10.3390/electronics15225383",
        "abstract",
    ),
    "S1": (
        "A high-performance generalized discontinuous PWM algorithm",
        1998,
        "https://doi.org/10.1109/28.720446",
        "body",
    ),
    "S2": (
        "Performance Evaluation of SiC-Based Two-Level VSIs with Generalized Carrier-Based PWM Strategies in "
        "Motor Drive Applications",
        2022,
        "https://doi.org/10.3390/electronics11244136",
        "abstract",
    ),
    "S3": (
        "Dead-time Compensation Method for Bus-clamping Modulated Voltage Source Inverter",
        2023,
        "https://arxiv.org/abs/2307.11868",
        "abstract",
    ),
    "S4": (
        "Variable Switching Frequency PWM for Three-Phase Converters Based on Current Ripple Prediction",
        2013,
        "https://doi.org/10.1109/tpel.2013.2240701",
        "abstract",
    ),
    "S6": (
        "Adaptive Determination of Optimum Switching Frequency in SiC-PWM-Based Motor Drives: A "
        "Speed-Dependent Core Loss Correction Approach",
        2025,
        "https://doi.org/10.1109/ojies.2025.3569349",
        "body",
    ),
    "S8": (
        "Enhancing Overload Capability of Electric Truck Inverters via Active Thermal Control",
        2025,
        "https://doi.org/10.1109/vppc66000.2025.11392945",
        "body",
    ),
    "S9": (
        "Active temperature control of inverters for applications in electric drives: Action on modulation strategies",
        2024,
        "https://doi.org/10.20906/cba2024/4485",
        "body",
    ),
    "S13": (
        "Switching Frequency Limitation with Finite Control Set Model Predictive Control via Slack Variables",
        2023,
        "https://arxiv.org/abs/2312.05916",
        "body",
    ),
    "S14": (
        "Improved Multi-step FCS-MPCC with Disturbance Compensation for PMSM Drives: Methods and Experimental "
        "Validation",
        2022,
        "https://arxiv.org/abs/2205.07213",
        "body",
    ),
    "S15": (
        "Performance Assessment of FCS-MPCC and DPCC for PMSM Drives Under Matched Average Switching Frequency "
        "Conditions",
        2026,
        "https://doi.org/10.67047/tepes.1922611",
        "body",
    ),
    "S16": (
        "Review of Cost-Function Design in Finite-Control-Set MPC for PMSM Drives",
        2026,
        "https://doi.org/10.1109/access.2026.3704303",
        "abstract",
    ),
    "S27": (
        "An Enhanced Model Predictive Torque Control With Online Loss Minimization Tracking for SPMSM Drive",
        2024,
        "https://doi.org/10.1109/tie.2024.3493173",
        "abstract",
    ),
    "S30": (
        "PWM Dead Times in Automotive Traction Inverters using IGBT, SiC MOSFET, or Si/SiC Fusion Switch Power Modules",
        2026,
        "https://doi.org/10.1049/pel2.70185",
        "abstract",
    ),
    "S34": (
        "Decoupled Discrete Current Control for AC Drives at Low Sampling-to-Fundamental Frequency Ratios",
        2022,
        "https://doi.org/10.1109/jestpe.2022.3179184",
        "abstract",
    ),
    "S37": (
        "A Deadbeat PI Controller With Modified Feedforward for PMSM Under Low Carrier Ratio",
        2021,
        "https://doi.org/10.1109/access.2021.3075486",
        "abstract",
    ),
    "S38": (
        "From Continuous Design to Delay-Aware Discrete Synthesis: Guaranteed High-Bandwidth Joint Control for "
        "PMSM Drives",
        2026,
        "https://arxiv.org/abs/2608.14937",
        "body",
    ),
    "S39": (
        "Robust sensorless control of high speed PMSM drives under low carrier ratios and parameter uncertainties",
        2026,
        "https://doi.org/10.1038/s41598-026-41212-z",
        "body",
    ),
    "S41": (
        "Observers for High-Speed Sensorless PMSM Drives: Design Methods, Tuning Challenges and Future Trends",
        2021,
        "https://doi.org/10.1109/access.2021.3072360",
        "abstract",
    ),
    "S42": (
        "Equivalent Flux Compensation for SPMSM Sensorless Control under Parameter Mismatch",
        2026,
        "https://arxiv.org/abs/2609.29313",
        "abstract",
    ),
    "S45": (
        "An Improved Deadbeat Predictive Current Control of PMSM Drives Based on the Ultra-local Model",
        2023,
        "https://doi.org/10.23919/cjee.2023.000020",
        "abstract",
    ),
}
