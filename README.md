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

* The site is primarily designed for municipalities participating in FIR reporting, not for people interested in exploring and analyzing the data.
* The detailed instructions that provide more detail on what is included in each line are in PDF format; cross-referencing the instructions and data reports is therefore quite difficult. This increases the difficulty of understanding data that already requires users to understand the structure of municipal governments, standards for municipal accounting, and to have background knowledge on municipal finances.
* There is no metadata to help analyze the data by particular themes. For example, data relating to health programs and investments may be located on multiple different schedules, requiring the user to parse through all the schedules to ensure that they have all the relevant information for a particular domain of inquiry.
* Querying on specific areas of interest often requires compiling multiple open data files, then querying on the combined file. There is no ability (aside from the pre-provided reports and dashboards) to make custom queries directly on the full dataset, and there is no open data file for the full, multi-year dataset.
* The full FIR dataset (or even some per-year files) are large enough that they can be hard to work with. For example, many per-year files are too large to store in version control (e.g. requiring Git Large File Storage), and analyzing the full dataset with in-memory tools such as Pandas and R may be more memory-intensive most personal computers can handle.
* Understanding the relationships between local and regional municipal governments requires pulling in and matching on external data.

## Opportunities for this project

* Prioritize users who are interested in exploring and analyzing the data, e.g. researchers, interested citizens, and policy-makers. Understand their needs and improve usability by testing with these users. For example, if most municipal finance researchers already use one particular software package for financial or statistical analysis, build tools with that software in mind.
* Develop and publish guides designed for these users so that they can easily learn about the FIR data and other important background information.
* Extract the information about what is in each line from the instructions PDF and make them easily accessible when users are exploring the data. Going from "what does this line mean" to an explanation should be one click.
* Add in useful metadata to help query for related information across multiple schedules.
* Make it easy for users to query and analyze FIR data using a regular personal computer by some combination of:
  * loading the open data into an actual database that can be queried against,
  * generating a single data file that can be stored in an S3-compatible cloud service and queried using tools like DuckDB, and/or
  * creating additional extracts that are not currently provided on the FIR web page
* Directly add in other useful data sources - e.g. relationships between local and regional governments, geodata on municipal boundaries for mapping, etc.
* Give users easy ways to supplement and link the FIR data to other sources, e.g. census data, concordances with financial datasets published by municipalities; and allow users to annotate values to provide additional context (e.g. linking to a council decision to create a levy on the first fiscal that the levy revenue appears)