import base64
import re
import shutil
import subprocess
import tempfile
from datetime import date
from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd
import requests
import streamlit as st
from jinja2 import Environment, FileSystemLoader

GOOGLE_SCRIPT_URL = st.secrets["GOOGLE_SCRIPT_URL"]
UPLOAD_TOKEN = st.secrets["UPLOAD_TOKEN"]

def post_to_drive_script(
    data: dict,
    timeout: int = 120,
) -> dict:
    """
    Send a request to the Google Apps Script web app.
    """
    response = requests.post(
        GOOGLE_SCRIPT_URL,
        data={
            "token": UPLOAD_TOKEN,
            **data,
        },
        timeout=timeout,
    )

    if not response.ok:
        raise RuntimeError(
            f"Google Drive request returned HTTP "
            f"{response.status_code}:\n"
            f"{response.text}"
        )

    try:
        result = response.json()
    except ValueError as error:
        raise RuntimeError(
            "Google Apps Script did not return valid JSON.\n\n"
            f"Response received:\n{response.text}"
        ) from error

    if not result.get("success"):
        raise RuntimeError(
            result.get(
                "error",
                "Unknown Google Drive error.",
            )
        )

    return result

def reserve_drive_report_number(
    department: str,
    report_type: str,
    report_title: str,
) -> dict:
    """
    Reserve the next report number in the correct Drive folder.
    """
    return post_to_drive_script(
        {
            "action": "reserve_number",
            "department": department,
            "report_type": report_type,
            "report_title": report_title,
        }
    )

def upload_reserved_pdf_to_drive(
    pdf_path: str | Path,
    reservation_id: str,
) -> dict:
    pdf_path = Path(pdf_path)

    if not pdf_path.is_file():
        raise FileNotFoundError(
            f"PDF does not exist: {pdf_path}"
        )

    if not reservation_id:
        raise ValueError(
            "Python did not receive a reservation ID."
        )

    encoded_pdf = base64.b64encode(
        pdf_path.read_bytes()
    ).decode("utf-8")

    return post_to_drive_script(
        {
            "action": "upload_pdf",
            "reservation_id": reservation_id,
            "file": encoded_pdf,
        },
        timeout=180,
    )

def cancel_drive_reservation(
    reservation_id: str,
) -> None:
    """
    Remove an unused reservation if PDF generation fails.
    """
    post_to_drive_script(
        {
            "action": "cancel_reservation",
            "reservation_id": reservation_id,
        }
    )

# =========================================================
# Folder paths
# =========================================================

BASE_DIR = Path(__file__).resolve().parent
TEMPLATE_DIR = BASE_DIR / "templates"
OUTPUT_DIR = BASE_DIR / "outputs"
STATIC_DIR = BASE_DIR / "static"

TEMPLATE_DIR.mkdir(parents=True, exist_ok=True)
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
STATIC_DIR.mkdir(parents=True, exist_ok=True)


# =========================================================
# Report configuration
# =========================================================

SUBTEAMS = [
    "Avionics",
    "Structures",
    "Recovery",
    "General",
]

SUBTEAM_CODES = {
    "Avionics": "A",
    "Structures": "S",
    "Recovery": "R",
    "General": "G",
}

REPORT_TYPES = [
    "Testing Report",
    "Simulation Report",
    "Design Report",
    "Project Outline Report",
    "Project Completion Report",
]

REPORT_CODES = {
    "Testing Report": "T",
    "Simulation Report": "S",
    "Design Report": "D",
    "Project Outline Report": "O",
    "Project Completion Report": "C",
}

REPORT_TEMPLATES = {
    "Testing Report": "testing_report.tex.j2",
    "Simulation Report": "simulation_report.tex.j2",
    "Design Report": "design_report.tex.j2",
    "Project Outline Report": "project_outline_report.tex.j2",
    "Project Completion Report": "project_completion_report.tex.j2",
}


# =========================================================
# Utility functions
# =========================================================

def latex_escape(value):
    """
    Escape characters that have special meaning in LaTeX.
    """
    if value is None:
        return ""

    value = str(value)

    replacements = {
        "\\": r"\textbackslash{}",
        "&": r"\&",
        "%": r"\%",
        "$": r"\$",
        "#": r"\#",
        "_": r"\_",
        "{": r"\{",
        "}": r"\}",
        "~": r"\textasciitilde{}",
        "^": r"\textasciicircum{}",
    }

    escaped = "".join(
        replacements.get(character, character)
        for character in value
    )

    escaped = escaped.replace("\r\n", "\n")
    escaped = escaped.replace("\r", "\n")
    escaped = escaped.replace("\n", "\n\n")

    return escaped


def safe_filename(value):
    """
    Convert text into a safe filename.
    """
    value = str(value).strip()

    for character in '<>:"/\\|?*':
        value = value.replace(character, "_")

    value = value.replace(" ", "_")

    while "__" in value:
        value = value.replace("__", "_")

    return value.strip("._") or "report"


def create_report_prefix(subteam, report_type):
    """
    Create the category prefix without the report number.

    Examples:
        RAT - Avionics testing report
        RAS - Avionics simulation report
        RSD - Structures design report
    """
    return (
        "R"
        + SUBTEAM_CODES[subteam]
        + REPORT_CODES[report_type]
    )


def find_next_report_number(output_directory, report_prefix):
    """
    Find the lowest unused report number for the selected report category.

    Both files and folders inside OUTPUT_DIR are checked recursively.

    For example, if these reports exist:

        RAT_001_VEGA_TEST.pdf
        RAT_003_LOAD_TEST.pdf

    the next report number will be 002.
    """
    used_numbers = set()

    # Matches names such as:
    # RAT_001
    # RAT_001_VEGA_TEST.pdf
    # RAT_001_VEGA_TEST_ab12cd34
    pattern = re.compile(
        rf"^{re.escape(report_prefix)}_(\d{{3}})(?:_|\.|$)",
        re.IGNORECASE,
    )

    if not output_directory.exists():
        return 1

    for path in output_directory.rglob("*"):
        match = pattern.match(path.name)

        if match:
            used_numbers.add(int(match.group(1)))

    next_number = 1

    while next_number in used_numbers:
        next_number += 1

    return next_number


def create_report_code(subteam, report_type, report_number):
    """
    Create the complete report code.

    Example:
        RAT_001
    """
    report_prefix = create_report_prefix(
        subteam,
        report_type,
    )

    return f"{report_prefix}_{report_number:03d}"

def safe_report_title(value):
    """
    Convert a report title into a consistent filename component.

    Example:
        "VEGA Test" -> "VEGA_TEST"
    """
    value = str(value).strip().upper()

    # Replace anything other than letters, numbers, hyphens
    # and underscores with an underscore.
    value = re.sub(r"[^A-Z0-9_-]+", "_", value)

    # Remove duplicate underscores.
    value = re.sub(r"_+", "_", value)

    return value.strip("_") or "UNTITLED"

def save_uploaded_file(uploaded_file, destination_folder):
    """
    Save a Streamlit uploaded file.
    """
    destination_folder.mkdir(parents=True, exist_ok=True)

    original_name = Path(uploaded_file.name).name
    safe_name = safe_filename(original_name)

    extension = Path(original_name).suffix.lower()

    if extension and not safe_name.lower().endswith(extension):
        safe_name = f"{Path(safe_name).stem}{extension}"

    output_path = destination_folder / safe_name

    counter = 1

    while output_path.exists():
        output_path = destination_folder / (
            f"{Path(safe_name).stem}_{counter}"
            f"{Path(safe_name).suffix}"
        )
        counter += 1

    output_path.write_bytes(uploaded_file.getbuffer())

    return output_path


def generate_chart(csv_path, output_path):
    """
    Generate a basic chart from the first two CSV columns.
    """
    dataframe = pd.read_csv(csv_path)

    if len(dataframe.columns) < 2:
        raise ValueError(
            "The CSV must contain at least two columns."
        )

    x_column = dataframe.columns[1]
    y_column = dataframe.columns[2]

    plt.figure(figsize=(12, 4.2))
    plt.plot(
        dataframe[x_column],
        dataframe[y_column],
        marker="o",
    )
    plt.title(f"{y_column} by {x_column}")
    plt.xlabel(x_column)
    plt.ylabel(y_column)
    plt.xticks(rotation=45)
    plt.tight_layout()
    plt.savefig(
        output_path,
        dpi=200,
        bbox_inches="tight",
    )
    plt.close()

    return dataframe


def create_jinja_environment():
    """
    Create the Jinja environment used for LaTeX templates.
    """
    environment = Environment(
        loader=FileSystemLoader(str(TEMPLATE_DIR)),
        block_start_string="((*",
        block_end_string="*))",
        variable_start_string="(((",
        variable_end_string=")))",
        comment_start_string="((=",
        comment_end_string="=))",
        autoescape=False,
        trim_blocks=True,
        lstrip_blocks=True,
    )

    environment.filters["latex_escape"] = latex_escape

    return environment


def render_latex(
    context,
    output_tex_path,
    template_filename,
):
    """
    Render the selected LaTeX template.
    """
    environment = create_jinja_environment()
    template = environment.get_template(template_filename)

    rendered_document = template.render(context)

    output_tex_path.write_text(
        rendered_document,
        encoding="utf-8",
    )


def compile_pdf(tex_path):
    """
    Compile the LaTeX file twice using pdflatex.
    """
    command = [
        "pdflatex",
        "-interaction=nonstopmode",
        "-halt-on-error",
        tex_path.name,
    ]

    for _ in range(2):
        result = subprocess.run(
            command,
            cwd=tex_path.parent,
            capture_output=True,
            text=True,
        )

        if result.returncode != 0:
            log_path = tex_path.with_suffix(".log")

            if log_path.exists():
                log_text = log_path.read_text(
                    encoding="utf-8",
                    errors="replace",
                )
            else:
                log_text = "No LaTeX log was created."

            raise RuntimeError(
                f"{result.stdout}\n\n"
                f"{result.stderr}\n\n"
                f"{log_text}"
            )

    pdf_path = tex_path.with_suffix(".pdf")

    if not pdf_path.exists():
        raise FileNotFoundError(
            "The PDF was not created."
        )

    return pdf_path


def short_text_area(
    label,
    help_text=None,
    height=110,
    placeholder=None,
):
    return st.text_area(
        label,
        help=help_text,
        height=height,
        placeholder=placeholder,
    )


# =========================================================
# Short report forms
# =========================================================

def testing_report_form():
    sections = {}

    sections["objective"] = short_text_area(
        "Purpose of test",
        "Briefly state what was being tested and why.",
    )

    sections["setup"] = short_text_area(
        "Setup and procedure",
        "Briefly describe the equipment and method used.",
        height=130,
    )

    sections["results"] = short_text_area(
        "Main results",
        "Record the important measurements or observations.",
        height=130,
    )

    sections["conclusion"] = short_text_area(
        "Conclusion and next action",
        "State whether the test was successful and what happens next.",
    )

    return sections


def simulation_report_form():
    sections = {}

    sections["objective"] = short_text_area(
        "Purpose of simulation",
        "Briefly state what the simulation was intended to investigate.",
    )

    sections["model"] = short_text_area(
        "Model and assumptions",
        "State the software, model used and important assumptions.",
        height=130,
    )

    sections["results"] = short_text_area(
        "Main results",
        "Record the most important outputs.",
        height=130,
    )

    sections["conclusion"] = short_text_area(
        "Conclusion and next action",
        "State what the results mean and any required follow-up.",
    )

    return sections


def design_report_form():
    sections = {}

    sections["goal"] = short_text_area(
        "Design goal",
        "Briefly describe what the design must achieve.",
    )

    sections["requirements"] = short_text_area(
        "Key requirements",
        "List the most important technical or practical requirements.",
    )

    sections["design"] = short_text_area(
        "Selected design",
        "Briefly describe the chosen design and why it was selected.",
        height=130,
    )

    sections["verification"] = short_text_area(
        "Verification and next action",
        "State how the design will be checked and what remains to be done.",
    )

    return sections


def project_outline_report_form():
    """
    Collect the information required for a project outline report.

    This form is intentionally more detailed than the other short report
    forms because the outline acts as the planning and approval document for
    a project. Changes here affect only the Project Outline Report.
    """
    sections = {}

    sections["main_goal"] = short_text_area(
        "Main goal",
        "State the principal outcome the project must achieve.",
    )

    sections["description"] = short_text_area(
        "Project description",
        "Briefly describe the project scope, background and intended result.",
        height=130,
    )

    sections["responsible_person"] = st.text_input(
        "Person responsible",
        placeholder="Project lead",
    )

    sections["supporting_members"] = st.text_input(
        "Supporting members",
        placeholder="Optional",
    )

    sections["target_date"] = st.date_input(
        "Target completion date",
        value=date.today(),
        key="outline_target_date",
    )

    sections["status"] = st.selectbox(
        "Current status",
        [
            "Not started",
            "Planning",
            "In progress",
            "On hold",
        ],
        key="outline_status",
    )

    st.markdown("#### Deliverables")
    sections["deliverables"] = short_text_area(
        "Planned deliverables",
        "Enter one deliverable per line.",
        height=130,
        placeholder=(
            "Completed prototype\n"
            "Validated final design\n"
            "Manufacturing and test documentation"
        ),
    )

    st.markdown("#### Testing and verification")
    sections["testing_items"] = st.data_editor(
        pd.DataFrame(
            [
                {"Test or review": "", "Purpose / acceptance criterion": ""},
                {"Test or review": "", "Purpose / acceptance criterion": ""},
                {"Test or review": "", "Purpose / acceptance criterion": ""},
            ]
        ),
        num_rows="dynamic",
        hide_index=True,
        use_container_width=True,
        key="outline_testing_items",
        column_config={
            "Test or review": st.column_config.TextColumn(
                "Test or review",
                help="For example: bench test, simulation review or flight test.",
            ),
            "Purpose / acceptance criterion": st.column_config.TextColumn(
                "Purpose / acceptance criterion",
                help="State what will be checked and how success will be judged.",
            ),
        },
    )

    st.markdown("#### Timeline")
    sections["timeline_items"] = st.data_editor(
        pd.DataFrame(
            [
                {"Period": "", "Planned work": ""},
                {"Period": "", "Planned work": ""},
                {"Period": "", "Planned work": ""},
                {"Period": "", "Planned work": ""},
            ]
        ),
        num_rows="dynamic",
        hide_index=True,
        use_container_width=True,
        key="outline_timeline_items",
        column_config={
            "Period": st.column_config.TextColumn(
                "Period",
                help="Month, week, phase or milestone date.",
            ),
            "Planned work": st.column_config.TextColumn(
                "Planned work",
                help="Main activity or milestone for this period.",
            ),
        },
    )

    st.markdown("#### Technology")
    sections["technology_items"] = st.data_editor(
        pd.DataFrame(
            [
                {"Technology / method": "", "Application": ""},
                {"Technology / method": "", "Application": ""},
                {"Technology / method": "", "Application": ""},
            ]
        ),
        num_rows="dynamic",
        hide_index=True,
        use_container_width=True,
        key="outline_technology_items",
        column_config={
            "Technology / method": st.column_config.TextColumn(
                "Technology / method",
                help="Key design approach, material, process, software or mechanism.",
            ),
            "Application": st.column_config.TextColumn(
                "Application",
                help="Explain how it will be used in the project.",
            ),
        },
    )

    st.markdown("#### Cost")
    sections["cost_notes"] = short_text_area(
        "Cost assumptions or funding notes",
        "For example: sponsorship sought, stock material available, or labour excluded.",
        height=80,
    )

    sections["cost_items"] = st.data_editor(
        pd.DataFrame(
            [
                {"Factor": "", "Status": "Estimated", "Value": ""},
                {"Factor": "", "Status": "Estimated", "Value": ""},
                {"Factor": "", "Status": "Estimated", "Value": ""},
            ]
        ),
        num_rows="dynamic",
        hide_index=True,
        use_container_width=True,
        key="outline_cost_items",
        column_config={
            "Factor": st.column_config.TextColumn(
                "Factor",
                help="Item, quantity, service or other cost driver.",
            ),
            "Status": st.column_config.SelectboxColumn(
                "Status",
                options=["Known", "Estimated", "Sponsored", "Available"],
                required=False,
            ),
            "Value": st.column_config.TextColumn(
                "Value",
                help="Enter the value with units or currency, for example €25 or 4 m².",
            ),
        },
    )

    sections["total_cost"] = st.text_input(
        "Estimated total cost",
        placeholder="For example: €150",
    )

    sections["notes"] = short_text_area(
        "Additional notes",
        "Optional dependencies, risks, constraints or relevant information.",
        height=90,
    )

    return sections


def project_completion_report_form():
    sections = {}

    sections["main_goal"] = short_text_area(
        "Original project goal",
        "State what the project was intended to achieve.",
    )

    sections["description"] = short_text_area(
        "Work completed",
        "Briefly describe what was completed.",
        height=130,
    )

    sections["responsible_person"] = st.text_input(
        "Person responsible",
        placeholder="Project lead",
    )

    sections["supporting_members"] = st.text_input(
        "Supporting members",
        placeholder="Optional",
    )

    sections["completion_date"] = st.date_input(
        "Completion date",
        value=date.today(),
        key="completion_date",
    )

    sections["outcome"] = st.selectbox(
        "Project outcome",
        [
            "Completed successfully",
            "Completed with changes",
            "Partially completed",
            "Cancelled",
        ],
        key="project_outcome",
    )

    sections["result"] = short_text_area(
        "Final result",
        "Briefly record the final outcome, hardware or documents produced.",
        height=110,
    )

    sections["notes"] = short_text_area(
        "Remaining actions or notes",
        "Optional short record of outstanding work or lessons learned.",
        height=90,
    )

    return sections


# =========================================================
# Streamlit interface
# =========================================================

st.set_page_config(
    page_title="Eirspace Report Generator",
    layout="centered",
)

st.title("Eirspace Report Generator")

st.caption(
    "Create short, consistent engineering and project reports."
)

report_type = st.selectbox(
    "Report type",
    REPORT_TYPES,
)

subteam = st.selectbox(
    "Department",
    SUBTEAMS,
)

report_prefix = create_report_prefix(
    subteam,
    report_type,
)

report_number = find_next_report_number(
    OUTPUT_DIR,
    report_prefix,
)

report_code = create_report_code(
    subteam,
    report_type,
    report_number,
)


report_date = st.date_input(
    "Date of report",
    value=date.today(),
)

report_author = st.text_input(
    "Report author",
)

participants = st.text_input(
    "Other participants",
    placeholder="Optional",
)

if report_type == "Testing Report":
    report_subject = st.text_input(
        "Test title",
        placeholder="For example: Airframe Compression Test",
    )

elif report_type == "Simulation Report":
    report_subject = st.text_input(
        "Simulation title",
        placeholder="For example: Fin Flutter Simulation",
    )

elif report_type == "Design Report":
    report_subject = st.text_input(
        "Design title",
        placeholder="For example: Avionics Bay Design",
    )

elif report_type == "Project Outline Report":
    report_subject = st.text_input(
        "Project title",
        placeholder="For example: Composite Nosecone Development",
    )

else:
    report_subject = st.text_input(
        "Completed project title",
        placeholder="For example: Composite Nosecone Development",
    )


st.divider()
st.subheader("Report details")

if report_type == "Testing Report":
    report_sections = testing_report_form()

elif report_type == "Simulation Report":
    report_sections = simulation_report_form()

elif report_type == "Design Report":
    report_sections = design_report_form()

elif report_type == "Project Outline Report":
    report_sections = project_outline_report_form()

else:
    report_sections = project_completion_report_form()


# Default values are needed because the PDF-generation code
# refers to csv_file and image_files for every report type.
csv_file = None
image_files = []

# Project Outline Reports do not use CSV files or images.
if report_type != "Project Outline Report":
    st.divider()
    st.subheader("Attachments")

    csv_file = st.file_uploader(
        "Upload CSV data",
        type=["csv"],
        help=(
            "Optional. A graph generated from the CSV data "
            "will be added to the report."
        ),
    )

    image_files = st.file_uploader(
        "Upload images",
        type=[
            "png",
            "jpg",
            "jpeg",
            "webp",
            "bmp",
            "tif",
            "tiff",
        ],
        accept_multiple_files=True,
        help=(
            "Optional. Upload photographs, screenshots, "
            "drawings or plots."
        ),
    )




st.info(
    "The report ID will be assigned from Google Drive "
    "when the PDF is generated."
)


# =========================================================
# PDF generation
# =========================================================

if st.button(
    "Generate PDF",
    type="primary",
    use_container_width=True,
):
    errors = []
    reservation_id = None

    if not report_subject.strip():
        errors.append("Enter a report title.")

    if not report_author.strip():
        errors.append("Enter the report author.")

    if errors:
        for error in errors:
            st.error(error)

    else:
        # Recalculate immediately before generating. This reduces the chance
        # of using a number that has since been taken by another report.
        try:
            reservation = reserve_drive_report_number(
                department=subteam,
                report_type=report_type,
                report_title=report_subject,
            )

            report_code = reservation["reportCode"]
            report_number = int(
                reservation["reportNumber"]
            )
            reservation_id = reservation["reservationId"]

        except Exception as error:
            st.error(
                "A report number could not be reserved "
                "from Google Drive."
            )
            st.code(str(error))
            st.stop()

        safe_title = safe_report_title(report_subject)

        full_report_name = f"{report_code}_{safe_title}"

        submission_folder = OUTPUT_DIR / full_report_name
        documents_folder = submission_folder / "submitted_documents"

        # Remove any incomplete local copy left by an earlier failed attempt.
        if submission_folder.exists():
            shutil.rmtree(submission_folder)

        submission_folder.mkdir(
            parents=True,
            exist_ok=True,
        )

        documents_folder.mkdir(
            parents=True,
            exist_ok=True,
        )

        try:
            with tempfile.TemporaryDirectory() as temporary_directory:
                working_directory = Path(temporary_directory)

                template_filename = REPORT_TEMPLATES[report_type]
                tex_filename = template_filename.removesuffix(".j2")
                tex_path = working_directory / tex_filename

                chart_path = None
                table_rows = []
                table_columns = []

                # CSV
                if csv_file is not None:
                    saved_csv_path = save_uploaded_file(
                        csv_file,
                        documents_folder,
                    )

                    chart_path = working_directory / "chart.png"

                    dataframe = generate_chart(
                        saved_csv_path,
                        chart_path,
                    )

                    table_rows = dataframe.head(20).to_dict(
                        orient="records"
                    )

                    table_columns = list(dataframe.columns)

                # Images
                working_image_paths = []
                saved_image_paths = []

                for image_file in image_files or []:
                    saved_image_path = save_uploaded_file(
                        image_file,
                        documents_folder,
                    )

                    saved_image_paths.append(saved_image_path)

                    working_image_path = (
                        working_directory
                        / saved_image_path.name
                    )

                    shutil.copy2(
                        saved_image_path,
                        working_image_path,
                    )

                    working_image_paths.append(
                        working_image_path
                    )

                # Logo
                logo_source = (
                    STATIC_DIR
                    / "Eirspace_Logo.png"
                )

                logo_path = ""

                if logo_source.exists():
                    logo_destination = (
                        working_directory
                        / "Eirspace_Logo.png"
                    )

                    shutil.copy2(
                        logo_source,
                        logo_destination,
                    )

                    logo_path = logo_destination.as_posix()

                # Convert date fields inside report_sections.
                formatted_sections = {}

                for key, value in report_sections.items():
                    if isinstance(value, date):
                        formatted_sections[key] = value.strftime(
                            "%d %B %Y"
                        )
                    elif isinstance(value, pd.DataFrame):
                        # Remove completely blank rows before passing table data
                        # to Jinja. This is used by the Project Outline Report;
                        # the other report types continue to pass plain strings.
                        cleaned_dataframe = value.fillna("")
                        cleaned_dataframe = cleaned_dataframe[
                            cleaned_dataframe.apply(
                                lambda row: any(
                                    str(cell).strip()
                                    for cell in row
                                ),
                                axis=1,
                            )
                        ]
                        formatted_sections[key] = cleaned_dataframe.to_dict(
                            orient="records"
                        )
                    elif key == "deliverables":
                        formatted_sections[key] = [
                            line.strip()
                            for line in str(value).splitlines()
                            if line.strip()
                        ]
                    else:
                        formatted_sections[key] = value

                context = {
                    "report_code": report_code,
                    "full_report_name": full_report_name,
                    "report_type": report_type,
                    "report_title": report_subject,
                    "report_subject": report_subject,
                    "report_number": f"{report_number:03d}",
                    "report_date": report_date.strftime("%d %B %Y"),
                    "subteam": subteam,
                    "department": subteam,
                    "report_author": report_author,
                    "participants": participants,
                    "sections": formatted_sections,
                    "has_csv": csv_file is not None,
                    "chart_path": (
                        chart_path.as_posix()
                        if chart_path
                        else ""
                    ),
                    "table_rows": table_rows,
                    "table_columns": table_columns,
                    "has_images": len(working_image_paths) > 0,
                    "image_paths": [
                        path.as_posix()
                        for path in working_image_paths
                    ],
                    "logo_path": logo_path,
                }
                render_latex(
                    context,
                    tex_path,
                    template_filename,
                )

                pdf_path = compile_pdf(tex_path)

                final_pdf_path = (
                    submission_folder
                    / f"{full_report_name}.pdf"
                )

                final_pdf_path.write_bytes(
                    pdf_path.read_bytes()
                )

                # Save rendered LaTeX for future editing.
                final_tex_path = (
                    submission_folder
                    / f"{full_report_name}.tex"
                )

                final_tex_path.write_bytes(
                    tex_path.read_bytes()
                )

                st.success("PDF generated successfully.")

                try:
                    drive_result = upload_reserved_pdf_to_drive(
                        pdf_path=final_pdf_path,
                        reservation_id=reservation_id,
                    )

                    st.success(
                        f"{drive_result['fileName']} was uploaded "
                        "to Google Drive."
                    )

                    st.link_button(
                        "Open PDF in Google Drive",
                        drive_result["fileUrl"],
                        use_container_width=True,
                    )

                except Exception as upload_error:
                    st.warning(
                        "The PDF was generated locally, but the "
                        "Google Drive upload failed."
                    )
                    st.code(str(upload_error))

                st.download_button(
                    "Download PDF",
                    data=final_pdf_path.read_bytes(),
                    file_name=final_pdf_path.name,
                    mime="application/pdf",
                    use_container_width=True,
                )

                with st.expander(
                    "Saved report location"
                ):
                    st.code(str(submission_folder))

        except FileNotFoundError as error:
            st.error(
                "A required file could not be found."
            )
            st.code(str(error))

        except subprocess.SubprocessError as error:
            st.error(
                "LaTeX could not be run."
            )
            st.code(str(error))

        except Exception as error:
            if reservation_id:
                try:
                    cancel_drive_reservation(
                        reservation_id
                    )
                except Exception:
                    pass

            st.error(
                "The report could not be generated."
            )
            st.code(str(error))