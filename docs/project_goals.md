# Ontario Municipal Finances Explorer

## Goal

Make it easier for researchers, interested citizens, and policy-makers to explore the data available from [Ontario Municipal Financial Information Returns](https://efis.fma.csc.gov.on.ca/fir/index.php/en/financial-information-return-en/) ("FIR").

The FIR system includes data on "municipal financial position and activities, such as assets, liabilities, revenue, expenses, over the course of the previous fiscal year (based on the audited financial statements), as well as municipal statistical information."

## Benefits and Current Strengths of the FIR Site

The [Financial Information Return website](https://efis.fma.csc.gov.on.ca/fir/index.php/en/financial-information-return-en/) already does some basic things well:

* [Detailed instructions](https://efis.fma.csc.gov.on.ca/fir/index.php/en/municipal-reporting/fir-instructions/) on how the data is collected are posted publicly.
* [Individual submissions from Municipalities for each year](https://efis.fma.csc.gov.on.ca/fir/index.php/en/reports-and-dashboards/fir-by-year-and-municipality/) can be downloaded.
* [Multi-year reports](https://efis.fma.csc.gov.on.ca/fir/index.php/en/reports-and-dashboards/fir-multi-year-reports/) are available, including for the whole province and for regions.
* Some basic [interactive dashboards](https://efis.fma.csc.gov.on.ca/fir/index.php/en/reports-and-dashboards/dashboards/) are provided to dig into the data.
* A variety of [open data files](https://efis.fma.csc.gov.on.ca/fir/index.php/en/open-data/) are made available.

## Challenges with the FIR site

* **Target audience:** The site and its instructions documents are primarily designed for municipalities participating in FIR reporting, not for people interested in exploring and analyzing the data.
* **Missing definitions:** The instructions documents do not appear to contain a glossary or list of key terms.
* **Documentation is hard to use:** The instructions that provide more detail on what is included in each line are in PDF format; cross-referencing the instructions and data reports is therefore quite difficult. This increases the challenge of understanding data that already requires users to understand the structure of municipal governments, standards for municipal accounting, and to have background knowledge on municipal finances.
* **Open data is missing internal structure:** The data has a rich internal structure (e.g. lines that subtotal into other lines, lines cross-referenced across schedules, sections that provide alternative breakdowns of a line). This is described in the PDF instructions but is not reflected in the open data formats provided. As a result, the internal structure is harder to understand and navigate when using the open data as currently provided.
	* Schedule 83 ("Notes") specifically has notes that may be relevant to lines in other schedules, but reviewing them requires manual cross-referencing across schedules and manually identifying which line(s) and/or column(s) the notes apply to.
* **No supplemental metadata:** There is no metadata to help analyze the data by particular themes. For example, data relating to health programs and investments may be located on multiple different schedules, requiring the user to parse through all the schedules to ensure that they have all the relevant information for a particular domain of inquiry.
* **Data provided is hard to query:** Querying on specific areas of interest often requires compiling multiple open data files, then querying on the combined file. There is no ability (aside from the pre-provided reports and dashboards) to make custom queries directly on the full dataset, and there is no open data file for the full, multi-year dataset.
* **Data provided can be unwieldy:** The full FIR dataset (or even some per-year files) are large enough that they can be hard to work with. For example, many per-year files are too large to store in version control (e.g. requiring Git Large File Storage), and analyzing the full dataset with in-memory tools such as Pandas and R may be more memory-intensive than most personal computers can handle.

## Opportunities for this project

* **Target audience:** Prioritize users who are interested in exploring and analyzing the data, e.g. researchers, interested citizens, and policy-makers. Understand their needs and improve usability by testing with these users. For example, if most municipal finance researchers already use one particular software package for financial or statistical analysis, build tools with that software in mind.
* **Background guides:** Develop and publish guides designed for these users so that they can easily learn about the FIR data and other important background information.
* **Make instructions text easy to access:** Extract the information about what is in each line from the instructions PDF and make them easily accessible when users are exploring the data. Going from "what does this line mean" to an explanation should be one click.
	* Make this information searchable, along with the schedule, line, and column titles, to improve discoverability of key data points (e.g. using Pagefind or providing a search function through the API).
* **Define key terms:** Develop a glossary of key terms and publish it as part of the guides and/or integrate it into the descriptions loaded into the database.
* **Metadata and internal structure:** Add in useful metadata and build in the structural relationships between lines and columns to help query for related information across multiple schedules.
* **Improve data management, querying, and exploration:** Make it easy for users to query and analyze FIR data using a regular personal computer by some combination of:
  * loading the open data into an actual database that can be queried against directly or via a public API,
  * connecting the database to a multi-purpose analytics tool, such as Apache Superset,
  * generating a single data file that can be stored in an S3-compatible cloud service and queried using tools like DuckDB, and/or
  * creating additional extracts that are not currently provided on the FIR web page
* **Add supplemental data:** Directly add in other useful data sources - e.g. relationships between local and regional governments, geodata on municipal boundaries for mapping, etc.
* **Empower users to add context and link to complimentary data:** Give users easy ways to supplement and link the FIR data to other sources, e.g. census data, housing stats, concordances with financial datasets published by municipalities; and allow users to annotate values to provide additional context (e.g. linking to a council decision to create a levy on the first fiscal that the levy revenue appears)

## Additional Notes:

### Public Sector Accounting Standards
Several FIR instructions reference the public sector accounting standards handbook. The handbook is generally made available on a [paid subscription access basis by the Chartered Professional Accountants of Canada](https://cpastore-boutiquecpa.cpacanada.ca/UI/Publications.html?productId=13843). Copies are also [available at public reference libraries](https://tpl.bibliocommons.com/v2/record/S234C3132233) and [some university libraries](https://librarysearch.library.utoronto.ca/permalink/01UTORONTO_INST/1no0b6e/alma991107164259406196).

### AMO MIDAS Tool
The [Association of Ontario Municipalities](https://www.amo.on.ca/) provides the [Municipal Information & Data Analysis System (MIDAS)](https://midas.amo.on.ca/) , which is a web-based tool that provides access to FIR data. I first came across it when reading a research paper that referenced using this tool to access FIR data.

There appears to be a public MIDAS that allows for querying the full dataset based on one or more years, municipalities, and SLCs (i.e. data points for a particular **S**chedule, **L**ine, and **C**olumn); as well as a private version of MIDAS with more advanced reporting capabilities made available to AMO members only.

The public version of MIDAS mostly solves the problem of "loading the open data into an actual database that can be queried against ... via a public API", though it does not offer much contextual information about the data, other than the SLC hierarchy. 

My observations about the public version of MIDAS from initial testing:
* It returned an error when a large number of output SLCs were selected
* The disclosure-details interface for drilling down to individual SLCs was time-consuming to use; as was the year checkbox interface
* It offered a variety of export formats (CSV, Excel, and PDF), though the CSV format did not follow the convention of keeping the column headings in the first row. In fairness, the additional pre-header rows are provided to show the original query criteria (which is helpful), and there are not many elegant solutions for providing metadata along with an output CSV file. This is a key design decision that I will need to spend some time considering as well.
* The search functionality built into the municipality multi-select and the SLC selection interfaces was quite useful, even with the queryable SLC text only being the line and column names with the specific SLC code.
* The output helpfully normalizes the municipality names (e.g. using "City of Toronto" instead of "Toronto C" in the FIR source data)