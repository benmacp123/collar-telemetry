README

This data package is published by the Movebank Data Repository (www.datarepository.movebank.org). As of the time of publication, a version of this published animal tracking dataset, with additional data, can be viewed on Movebank (www.movebank.org) in the study "Vultures tagged in the southeastern United States" (Movebank Study ID 24797204). Individual attributes in the data files are defined below, in the NERC Vocabulary Server at http://vocab.nerc.ac.uk/collection/MVB and in the Movebank Attribute Dictionary at www.movebank.org/cms/movebank-content/movebank-attribute-dictionary. Metadata describing this data package are maintained at https://datacite.org.

This data package includes the following data files:
Vultures tagged in the southeastern United States_part-gps.csv
Vultures tagged in the southeastern United States_part-reference-data.csv

Data package citation:
Kluever BM. 2026. Data from: Study "Vultures tagged in the southeastern United States" [part]. Movebank Data Repository. https://doi.org/10.5441/001/1.666

These data are described in the following written publications:
Evans BA, Humphrey JS, Tillman EA, Avery ML, Kluever BM. 2024. Site‐specific space use and resource selection by black vultures (coragyps atratus) in the southeastern USA. Ibis. 166(1):129-45. https://doi.org/10.1111/ibi.13244

Oliver RY, Yanco SW, Ellis-Soto D, Jesmer BR, Cohen J, Gao S, Patchett R, Avgar T, Bildstein K, Bakner NW, et al. In revision. Interacting effects of human mobility and landscape modification on wildlife. In revision at Science, October 2025.

-----------

Terms of Use
As of the time of publication, this data package is licensed by the 
Creative Commons Zero (CC0 1.0) license: http://creativecommons.org/publicdomain/zero/1.0

View the data package online for the current license. Works published with this license should be appropriately cited following professional and ethical standards for academic citation. We highly recommend that you contact the data creator if possible if you will be re-using or re-analyzing data in this file. Researchers will likely be interested in learning about new uses of their data, might also have important insights about how to properly analyze and interpret their data, and/or might have additional data they would be willing to contribute to your project. Feel free to contact us at support@movebank.org if you need assistance contacting data owners.

For additional information about these data and expectations for use, see the General Movebank Terms of Use (movebank.org/cms/movebank-content/general-movebank-terms-of-use) and Movebank user agreement (https://www.movebank.org/cms/movebank-content/data-policy#user_agreement).

-----------

Data Attributes
These definitions come from the Movebank Attribute Dictionary, available at http://vocab.nerc.ac.uk/collection/MVB and www.movebank.org/node/2381.

algorithm marked outlier: Identifies events marked as outliers using a user-selected filter algorithm in Movebank. Outliers have the value TRUE. Information about how outliers were defined can be provided in 'outlier comments'.
Units: none
Entity described: event
URI: https://vocab.nerc.ac.uk/collection/MVB/current/MVB000011/

animal death comments: Comments about the death of the animal. Summary information can be reported in 'animal mortality date', 'animal mortality latitude', 'animal mortality longitude', and 'animal mortality type'.
Example: 'hit by a car'
Units: none
Entity described: individual
URI: https://vocab.nerc.ac.uk/collection/MVB/current/MVB000013/

animal ID: An individual identifier for the animal, provided by the data owner. Values are unique within the study. If the data owner does not provide an Animal ID, an internal Movebank animal identifier is sometimes shown.
Example: 'TUSC_CV5'
Units: none
Entity described: individual
URI: https://vocab.nerc.ac.uk/collection/MVB/current/MVB000016/

animal life stage: The age class or life stage of the animal at the beginning of the deployment. Can be years or months of age or terms such as 'adult', 'subadult' and 'juvenile'. Best practice is to define units in the values if needed (e.g. '2 years').
Example: 'juvenile, adult'
Units: none
Entity described: deployment
URI: https://vocab.nerc.ac.uk/collection/MVB/current/MVB000018/

animal mass: The mass of the animal, typically at the beginning of the deployment.
Example: '500'
Units: grams
Entity described: deployment
URI: https://vocab.nerc.ac.uk/collection/MVB/current/MVB000019/

animal mortality date: The known or estimated date on which the animal died. This may differ from the time of the end of the deployment, which is defined by 'deploy-off timestamp'.
Example: '2022-04-26'
Format: yyyy-MM-dd
Units: date (time and time zone not specified)
Entity described: individual
URI: https://vocab.nerc.ac.uk/collection/MVB/current/MVB000394/

animal mortality type: The likely immediate cause of death. Additional information can be provided using 'animal death comments'. Values are chosen from a controlled list:
bycatch = unintentional death of a non-target animal during fishing activities
capture = related to the capture and handling of the animal for the study
electrocution = electric shock
harvest = intentional killing by humans, for example through hunting, fishing or poaching
disease = related to a specific illness or terminal disease
natural-death = natural causes, not further specified
other = other
parasites = parasitic infection or disease, including parasitoidism
poison = accidental or deliberate exposure to a chemical substance
predation = killed by a predator or micropredator
starvation = lack of caloric energy intake
unknown = could not be determined
vehicle-collision = collision with a motor vehicle, watercraft, aircraft or other vehicle.
Format: controlled list
Entity described: animal
URI: https://vocab.nerc.ac.uk/collection/MVB/current/MVB000345/

animal ring ID: A number or color scheme for a band or ring attached to the animal. Color bands and other markings can be stored in 'animal marker ID'.
Example: '26225'
Units: none
Entity described: individual
URI: https://vocab.nerc.ac.uk/collection/MVB/current/MVB000022/

animal sex: The sex of the animal. Allowed values are m = male
f = female
u = unknown.
Format: controlled list
Entity described: individual
URI: https://vocab.nerc.ac.uk/collection/MVB/current/MVB000023/

animal taxon: The scientific name of the taxon on which the tag was deployed, as defined by the Integrated Taxonomic Information System www.itis.gov. If the species name can not be provided, this should be the lowest level taxonomic rank that can be determined and that is used in the ITIS taxonomy. Additional information can be provided using the term 'taxon detail'. The values 'test' and 'calibration' identify events relevant to animal tracking studies that should not be associated with a taxon.
Format: controlled list
Entity described: individual
URI: https://vocab.nerc.ac.uk/collection/MVB/current/MVB000024/

attachment type: The way a tag is attached to an animal. Details can be provided in 'attachment comments'. Values are chosen from a controlled list:
backpack-harness = The tag is attached to the animal using a backpack-style harness
collar = The tag is attached by a collar around the animal's neck
ear-tag = The tag is attached to the animal's ear
fin mount = The tag is attached to the animal's fin
glue = The tag is attached to the animal using glue
harness = The tag is attached to the animal using a harness
implant = The tag is placed under the skin of the animal
leg-band = The tag is attached as a leg band or ring
leg-loop-harness = The tag is attached to the animal using a leg-loop-style harness
none = No tag was attached, e.g., for observations using natural markings
other = The tag is attached using another method
subcutaneous-anchor = The tag is attached using one or more anchors attached underneath the animal's skin
suction-cup = The tag is attached using one or more suction cups
sutures = The tag is attached by one or more sutures
tape = The tag is attached to the animal using tape.
Format: controlled list
Entity described: deployment
URI: https://vocab.nerc.ac.uk/collection/MVB/current/MVB000052/

capture method: A description of the method or methods used to bait, trap or immobilize the animal in order to attach the tag.
Units: none
Entity described: deployment
URI: https://vocab.nerc.ac.uk/collection/MVB/current/MVB000397/

deploy off timestamp: The timestamp when the tag deployment ended. Data records recorded after this day and time are not associated with the animal related to the deployment. Values are typically defined by the data owner, and in some cases are created automatically during data import. Further information can be provided in 'deployment end type' and 'deployment end comments'.
Example: '2009-10-01 12:00:00.000'
Format: yyyy-MM-dd HH:mm:ss.SSS
Units: UTC or GPS time
Entity described: deployment
URI: https://vocab.nerc.ac.uk/collection/MVB/current/MVB000077/

deploy on latitude: The geographic latitude of the location where the animal was released. Intended primarily for cases in which the animal release location has higher accuracy than that derived from sensor data.
Example: '27.3516'
Units: decimal degrees, WGS84 reference system
Entity described: deployment
URI: https://vocab.nerc.ac.uk/collection/MVB/current/MVB000078/

deploy on longitude: The geographic longitude of the location where the animal was released. Intended primarily for cases in which the animal release location has higher accuracy than that derived from sensor data.
Example: '-97.3321'
Units: decimal degrees, WGS84 reference system
Entity described: deployment
URI: https://vocab.nerc.ac.uk/collection/MVB/current/MVB000079/

deploy on measurements: A list of additional measurements taken during capture of the animal at the start of the deployment. Recommended best practice is to define units and use a key:value encoding schema for a data interchange format such as JSON.
Example: "{"tarsusLengthInMillimeters":17.3, "wingChordInMillimeters":125}"
Units: not defined
Entity described: deployment
URI: https://vocab.nerc.ac.uk/collection/MVB/current/MVB000356/

deploy on person: The name of the person/people who attached the tag to the animal and began the deployment.
Example: 'G. Smith'
Units: none
Entity described: deployment
URI: https://vocab.nerc.ac.uk/collection/MVB/current/MVB000080/

deploy on timestamp: The timestamp when the tag deployment started. Data records recorded before this day and time are not associated with the animal related to the deployment. Values are typically defined by the data owner, and in some cases are created automatically during data import.
Example: '2008-08-30 18:00:00.000'
Format: yyyy-MM-dd HH:mm:ss.SSS
Units: UTC or GPS time
Entity described: deployment
URI: https://vocab.nerc.ac.uk/collection/MVB/current/MVB000081/

deployment end comments: Additional information about the end of a tag deployment. Also see 'deployment end type', 'animal death comments', and 'tag failure comments'.
Example: 'data transmission stopped after 108 days. Cause unknown'
Units: none
Entity described: deployment
URI: https://vocab.nerc.ac.uk/collection/MVB/current/MVB000083/

deployment end type: A categorical classification describing the end of the tag deployment on the animal. Best practice is to clarify how the 'deploy-off timestamp', if present, was chosen. Values are chosen from a controlled list:
analysis-end = the end time represents the end of the period of interest
captured = The tag remained on the animal but the animal was captured or confined
dead = The deployment ended with the death of the animal that was carrying the tag
dead/fall-off = The tag stopped moving, and it is not possible to determine whether it is due to death of the animal or unscheduled tag detachment
equipment-failure = The tag stopped working
fall-off = The attachment of the tag to the animal failed, and it fell of accidentally
other = other
released = The tag remained on the animal but the animal was released from captivity or confinement
removal = The tag was purposefully removed from the animal
scheduled-detachment = The tag was programmed to detach from the animal
transmission-end = The tag stopped transmitting usable data
unknown = The cause of the end of data availability or transmission is unknown.
Format: controlled list
Entity described: deployment
URI: https://vocab.nerc.ac.uk/collection/MVB/current/MVB000084/

deployment ID: A unique identifier for the deployment of a tag on animal, provided by the data owner. If the data owner does not provide a Deployment ID, an internal Movebank deployment identifier may sometimes be shown.
Example: 'Jane_42818'
Units: none
Entity described: deployment
URI: https://vocab.nerc.ac.uk/collection/MVB/current/MVB000085/

event ID: An identifier for the set of values associated with each event, i.e. sensor measurement. A unique event ID is assigned to every time-location or other time-measurement record in Movebank. If multiple measurements are included within a single row of a data file, they will share an event ID. If users import the same sensor measurement to Movebank multiple times, a separate event ID will be assigned to each.
Example: '14328243575'
Units: none
Entity described: event
URI: https://vocab.nerc.ac.uk/collection/MVB/current/MVB000103/

GPS HDOP: Horizontal dilution of precision provided by the GPS.
Example: '1.2'
Units: unitless
Entity described: event
URI: https://vocab.nerc.ac.uk/collection/MVB/current/MVB000118/

GPS satellite count: The number of GPS satellites used to estimate the location.
Example: '8'
Units: count
Entity described: event
URI: https://vocab.nerc.ac.uk/collection/MVB/current/MVB000120/

GPS VDOP: Vertical dilution of precision provided by the GPS.
Example: '1.9'
Units: unitless
Entity described: event
URI: https://vocab.nerc.ac.uk/collection/MVB/current/MVB000122/

ground speed: The estimated ground speed provided by the sensor or calculated between consecutive locations.
Example: '7.22'
Units: m/s
Entity described: event
URI: https://vocab.nerc.ac.uk/collection/MVB/current/MVB000124/

heading: The direction in which the tag is moving, in decimal degrees clockwise from north, as provided by the sensor or calculated between consecutive locations. Values range from 0-360: 0 = north, 90 = east, 180 = south, 270 = west.
Example: '315.88'
Units: degrees clockwise from north
Entity described: event
URI: https://vocab.nerc.ac.uk/collection/MVB/current/MVB000129/

height raw: Raw values for the height of the tag above ellipsoid or mean sea level, typically estimated by the tag. Values are stored as raw text values because non-numeric characters are used or processing is required to derive the correct height estimate. Best practice is to define values in the reference data.
Example: '425, 2D fix'
Units: not defined
Entity described: event
URI: https://vocab.nerc.ac.uk/collection/MVB/current/MVB000132/

import marked outlier: Identifies events as outliers. Outliers have the value TRUE. Typically used to import a record of outliers that were identified by the data provider or owner with automated methods outside of Movebank. Information about how outliers were defined can be provided in 'outlier comments'.
Units: none
Entity described: event
URI: https://vocab.nerc.ac.uk/collection/MVB/current/MVB000133/

location lat: The geographic latitude of the location as estimated by the sensor.
Example: '-41.0982423'
Units: decimal degrees, WGS84 reference system
Entity described: event
URI: https://vocab.nerc.ac.uk/collection/MVB/current/MVB000145/

location long: The geographic longitude of the location as estimated by the sensor. Positive values are east of the Greenwich Meridian, negative values are west of it.
Example: '-121.1761111'
Units: decimal degrees, WGS84 reference system
Entity described: event
URI: https://vocab.nerc.ac.uk/collection/MVB/current/MVB000146/

manipulation type: The way in which the animal was manipulated during the deployment. Additional information can be provided using 'manipulation comments'. Changes in manipulation status during deployment can be identified using 'manipulation status'. Values are chosen from a controlled list:
confined = The animal's movement was restricted to within a defined area
domesticated = The animal is domesticated, for example, is a house pet or part of a managed herd
manipulated-other = The animal was manipulated in some other way, such as a physiological manipulation
none = The animal received no treatment other than tag attachment and related measurements and sampling (if applicable)
reintroduction = The animal has been reintroduced as part of wildlife conservation or management efforts
relocated = The animal was released from a site other than the one at which it was captured.
Format: controlled list
Entity described: deployment
URI: https://vocab.nerc.ac.uk/collection/MVB/current/MVB000155/

manually marked outlier: Identifies events flagged manually as outliers, typically using the Event Editor in Movebank, and may also include outliers identified using other methods. Outliers have the value TRUE. Information about how outliers were defined can be provided in 'outlier comments'.
Units: none
Entity described: event
URI: https://vocab.nerc.ac.uk/collection/MVB/current/MVB000156/

Mw show in KML: Used by Microwave GPS tags to flag implausible locations. Allowed values are TRUE or FALSE
implausible locations have the value FALSE.
Units: none
Entity described: event
URI: https://vocab.nerc.ac.uk/collection/MVB/current/MVB000159/

outlier comments: A description or reference for methods used to define outliers in 'manually marked outlier', 'algorithm marked outlier', 'import marked outlier' and/or 'manually marked valid'. If outliers were removed prior to import, this field can be used to describe which data were excluded.
Example: 'Movebank value range filter set to flag records with GPS HDOP => 20, retaining records with null values.'
Units: none
Entity described: deployment
URI: https://vocab.nerc.ac.uk/collection/MVB/current/MVB000374/

sensor type: The type of sensor with which data were collected. All sensors are associated with a tag id, and tags can contain multiple sensor types. Each event record in Movebank is assigned one sensor type. If values from multiple sensors are reported in a single event, the primary sensor is used. Values are chosen from a controlled list:
acceleration = The sensor collects acceleration data
accessory-measurements = The sensor collects accessory measurements, such as battery voltage
acoustic-telemetry = The sensor transmits an acoustic signal that is detected by receivers to determine location
argos-doppler-shift = The sensor location is estimated by Argos using Doppler shift
atlas-geolocation = The sensor location is estimated by an ATLAS system
barometer = The sensor records air or water pressure
bird-ring = The animal is identified by a band or ring that has a unique identifier
derived = Information is derived from other sensor data
geolocation-api = The location is determined based on detection by nearby cell towers or other wireless network connectors using the World Wide Web Consortium Geolocation API Recommendation
gnss = The sensor uses one or more global navigation satellite systems to determine location
gps = The sensor uses GPS to determine location
gyroscope = The sensor records angular velocity
heart-rate = The sensor records or is used to calculate heart rate
magnetometer = The sensor records the magnetic field
natural-mark = The animal is identified by a unique natural marking
orientation = Quaternion components describing the orientation of the tag are derived from accelerometer and gyroscope measurements
proximity = The sensor identifies proximity to other tags
radio-transmitter = The sensor transmits a radio signal that is detected by receivers to determine location
sigfox-geolocation = The sensor location is determined by Sigfox using the received signal strength indicator
solar-geolocator = The sensor collects light levels, which are used to determine position (for processed locations)
solar-geolocator-raw = The sensor collects light levels, which are used to determine position (for raw light-level measurements)
solar-geolocator-twilight = The sensor collects light levels, which are used to determine position (for twilights calculated from light-level measurements)
tdr = The sensor is a time-depth recorder.
Format: controlled list
Entity described: event
URI: https://vocab.nerc.ac.uk/collection/MVB/current/MVB000170/

study name: The name of the study in Movebank.
Example: 'Coyotes, Kays and Bogan, Albany NY'
Units: none
Entity described: study
URI: https://vocab.nerc.ac.uk/collection/MVB/current/MVB000173/

study site: A location such as the deployment site, study site, or colony name.
Example: 'Pickerel Island North'
Units: none
Entity described: deployment
URI: https://vocab.nerc.ac.uk/collection/MVB/current/MVB000175/

tag ID: A unique identifier for the tag, provided by the data owner. If the data owner does not provide a tag ID, an internal Movebank tag identifier may sometimes be shown.
Example: '2342'
Units: none
Entity described: tag
URI: https://vocab.nerc.ac.uk/collection/MVB/current/MVB000181/

tag manufacturer name: The company or person that produced the tag.
Example: 'Holohil'
Units: none
Entity described: tag
URI: https://vocab.nerc.ac.uk/collection/MVB/current/MVB000183/

tag mass: The mass of the tag. Can be used with 'tag mass total' to define the mass of the tag separately from that of the tag with additional hardware.
Example: '24'
Units: grams
Entity described: tag
URI: https://vocab.nerc.ac.uk/collection/MVB/current/MVB000184/

tag model: The model of the tag.
Example: 'T61'
Units: none
Entity described: tag
URI: https://vocab.nerc.ac.uk/collection/MVB/current/MVB000185/

tag readout method: The way the data are received from the tag. Values are chosen from a controlled list:
ISS = Data are transferred via the International Space Station; LPWAN = Data are transferred through a low-power wide-area network, such as LoRa or Sigfox
multiple = Data are acquired using multiple methods
none = Data are obtained without use of an animal-borne tag, such as by observing a unique marking
other-wireless = Data are transferred via another form of wireless data transfer, such as a VHF transmitter/receiver
phone-network = Data are transferred via a phone network, such as GSM or AMPS
satellite = Data are transferred via satellite
tag-retrieval = The tag must be physically retrieved in order to obtain the data
telemetry-network = Data are obtained through a radio or acoustic telemetry network; Wi-Fi/Bluetooth = Data are transferred via a local Wi-Fi or Bluetooth system.
Format: controlled list
Entity described: deployment
URI: https://vocab.nerc.ac.uk/collection/MVB/current/MVB000188/

timestamp: The date and time corresponding to a sensor measurement or an estimate derived from sensor measurements.
Example: '2008-08-14 18:31:00.000'
Format: yyyy-MM-dd HH:mm:ss.SSS
Units: UTC or GPS time
Entity described: event
URI: https://vocab.nerc.ac.uk/collection/MVB/current/MVB000200/

visible: Determines whether an event is visible on the Movebank map. Allowed values are TRUE or FALSE. Values are calculated automatically, with TRUE indicating the event has not been flagged as an outlier by 'algorithm marked outlier', 'import marked outlier' or 'manually marked outlier', or that the user has overridden the results of these outlier attributes using 'manually marked valid' = TRUE.
Units: none
Entity described: event
URI: https://vocab.nerc.ac.uk/collection/MVB/current/MVB000209/

-----------

More Information
For more information about this repository, see www.movebank.org/cms/movebank-content/data-repository, the FAQ at https://www.datarepository.movebank.org/faq, or contact us at support@movebank.org.