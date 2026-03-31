## Data Profiling

- 'MARSYEAR': The FIR reporting year
  - (2000 - 2023)

- 'ASSESSMENT_CODE': Four digit assessment code

The four-digit code made up of two portions: the first two digits describe the geographic Upper Tier in which the municipality is located, the second pair of digits uniquely describe the Lower Tier Municipality within the geographic Upper Tier.

Mississauga: 2105
Brampton: 2110
Peel: 2100

- 'MUNICIPALITY_DESC': Municipality Name
  - e.g. "Toronto C", "Rockcliffe Park V", "Peel R"

- 'MUNID': Municipal ID - five digit code
  - e.g. Region of Peel is "21000" Seems very similar to assessment code.

- 'MSO_NUMBER': 2 digit code to identify the Municipal Service Office
  - (probably not relevant for analysis?)

- 'SGC_CODE': Standard Geographic Code
  - often, but not always, the same as MUNID

- 'UT_NUMBER': Upper Tier Number
  - First two digits of assessment code?

- **'MTYPE_CODE': Municipal Type Code**
  - 0 = Upper Tier
  - 1 = City
  - 3 = Separated Town
  - 4 = Town
  - 5 = Village
  - 6 = Township

- 'TIER_CODE': Code to indicate tier of the municipality
  - LT (7.2M records) - lower tier
  - ST (5.5M records) - single tier
  - UT (0.8M records) - upper tier

- 'LAST_UPDATE_DATE': The date that the data for the municipality was last updated for the reporting year.
- 'SCHEDULE_DESC': The name of the FIR schedule.
- 'SUB_SCHEDULE_DESC': The sub-schedule description where applicable,
- 'SCHEDULE_LINE_DESC': Line description
- 'SCHEDULE_COLUMN_DESC': Column heading

- 'SLC': SLC identifies the datapoint including Schedule, Line and Column.
  - The SLC takes the following format: **slc.02X.L0020.C01.02**
  - all slc references begin with "slc."
  - 02X refers to the schedule number. In this example it is referring to Schedule 02. In most cases, the schedule number is followed by an X. i.e. Schedule 10 would be slc.10X. However, where a schedule is divided into different parts (i.e. Schedule 26 is divided into two tabs in the FIR template; Schedule 26A and Schedule 26B) the schedule portion of the slc will be slc.26A and slc.26B. Other schedules where this applies include: Schedule 51, Schedule 72 , Schedule 74, Schedule 77 and Schedule 80.
  - L0020 refers to the line number. In this example the line number is 0020
  - C01.02 refers to the section and column number. In most cases the section will 01. However where a schedule has distinct sections, the section number will change. For example, Schedule 20 is divided into different sections with varying number of columns in each section.

- 'DATATYPE_DESC': The datatype description identifies the data as one of the following: text, currency, non-currency, percentage
- 'AMOUNT': If the datatype is not text the amount will be found here, otherwise this will be blank.
- 'VALUE_TEXT': If the datatype is text the text value will be found here, otherwise this will be blank.