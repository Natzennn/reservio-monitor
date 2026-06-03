def extract_events_from_dom(page):
    text = page.locator("body").inner_text(timeout=20000)
    text = normalize_text(text)

    lines = [
        normalize_text(line)
        for line in text.splitlines()
        if normalize_text(line)
    ]

    date_regex = re.compile(
        r"^(poniedziałek|wtorek|środa|czwartek|piątek|sobota|niedziela),\s+"
        r"(sty|lut|mar|kwi|maj|cze|lip|sie|wrz|paź|paz|lis|gru)\s+"
        r"\d{1,2},\s+\d{4}$",
        re.IGNORECASE,
    )

    time_regex = re.compile(
        r"\b\d{1,2}:\d{2}\s*-\s*\d{1,2}:\d{2}\b"
    )

    availability_regex = re.compile(
        r"\b\d+\s*(?:"
        r"wolne miejsce|wolne miejsca|wolnych miejsc|"
        r"miejsce dostępne|miejsca dostępne|miejsc dostępnych"
        r")\b",
        re.IGNORECASE,
    )

    found = []

    current_date = None
    current_title = None
    current_time = None
    current_availability = None
    current_is_full = False

    def flush_event():
        nonlocal current_title, current_time, current_availability, current_is_full

        if (
            current_date
            and current_title
            and current_time
            and current_availability
            and not current_is_full
        ):
            found.append(
                f"{current_date} | {current_time} | {current_title} | {current_availability}"
            )

        current_title = None
        current_time = None
        current_availability = None
        current_is_full = False

    noise = {
        "tanie treningi strzelectwa dynamicznego",
        "przemysław",
        "z powrotem",
        "strona główna",
        "/",
        "wydarzenia",
        "szukaj...",
        "pokaż szczegóły",
        "wybierz dzień",
        "obsługiwane przez",
        "reservio business",
        "kalendarz wydarzeń | tanie treningi strzelectwa dynamicznego",
    }

    for line in lines:
        lower = line.lower()

        if date_regex.match(line):
            flush_event()
            current_date = line
            continue

        if "w tym dniu nie ma żadnych wydarzeń" in lower:
            flush_event()
            continue

        if lower in noise:
            continue

        if lower.startswith("© copyright"):
            continue

        if "masz własny biznes" in lower:
            continue

        if lower in ["pon.", "wt.", "śr.", "czw.", "pt.", "sob.", "niedz."]:
            continue

        if re.fullmatch(r"\d+", line):
            continue

        if re.fullmatch(r"\d+\s*zł", line, re.IGNORECASE):
            continue

        if "pełne obłożenie" in lower:
            current_is_full = True
            continue

        if time_regex.search(line):
            current_time = line
            continue

        if availability_regex.search(line):
            current_availability = line
            continue

        # Tytuł wydarzenia — bierzemy pierwszą sensowną linię po dacie.
        if current_date and not current_title:
            current_title = line
            continue

    flush_event()

    unique = []
    seen = set()

    for event in found:
        key = event.lower()

        if key not in seen:
            seen.add(key)
            unique.append(event)

    return unique
