README

This data file is published by the Movebank Data Repository (www.datarepository.movebank.org). As of the time of publication, a version of this published animal tracking dataset can be viewed on Movebank (www.movebank.org) in the study "ThermochronTracking Elephants Kruger 2007" (Movebank Study ID 736029750). Individual attributes in the data files are defined below, in the NERC Vocabulary Server at http://vocab.nerc.ac.uk/collection/MVB and in the Movebank Attribute Dictionary at www.movebank.org/node/2381. Metadata describing this data package are maintained at https://datacite.org.

This data package includes the following data files:
ThermochronTracking Elephants Kruger 2007.csv
ThermochronTracking Elephants Kruger 2007-reference-data.csv

Data package citation:
Slotow R, Thaker M, Vanak AT (2019) Data from: Fine-scale tracking of ambient temperature and movement reveals shuttling behavior of elephants to water. Movebank Data Repository. https://doi.org/10.5441/001/1.403h24q5

These data are described in the following written publication:
Thaker M, Gupte PR, Prins HHT, Slotow R, Vanak AT (2019) Fine-scale tracking of ambient temperature and movement reveals shuttling behavior of elephants to water. Frontiers in Ecology and Evolution 7:4. https://doi.org/10.3389/fevo.2019.00004

-----------

Terms of Use
This data file is licensed by the Creative Commons Zero (CC0 1.0) license. The intent of this license is to facilitate the re-use of works. The Creative Commons Zero license is a "no rights reserved" license that allows copyright holders to opt out of copyright protections automatically extended by copyright and other laws, thus placing works in the public domain with as little legal restriction as possible. However, works published with this license must still be appropriately cited following professional and ethical standards for academic citation.

We highly recommend that you contact the data creator if possible if you will be re-using or re-analyzing data in this file. Researchers will likely be interested in learning about new uses of their data, might also have important insights about how to properly analyze and interpret their data, and/or might have additional data they would be willing to contribute to your project. Feel free to contact us at support@movebank.org if you need assistance contacting data owners.

See here for the full description of this license
http://creativecommons.org/publicdomain/zero/1.0

-----------

Data Attributes
These definitions come from the Movebank Attribute Dictionary, available at www.movebank.org/node/2381.

animal comments: Additional information about the animal that is not described by other reference data terms.
example: sibling of #1423

animal ID: An individual identifier for the animal, provided by the data owner. This identifier can be a ring number, a name, the same as the associated tag ID, etc. If the data owner does not provide an Animal ID, an internal Movebank animal identifier is sometimes shown.
example: 91876A, Gary
same as: individual local identifier

animal life stage: The age class or life stage of the animal at the beginning of the deployment. Can be years or months of age or terms such as "adult", "subadult" and "juvenile". Best practice is to define units in the values if needed (e.g. "2 years").
example: juvenile, adult
units: not defined

animal sex: The sex of the animal. Allowed values are
m: male
f: female

animal taxon: The scientific name of the species on which the tag was deployed, as defined by the Integrated Taxonomic Information System (ITIS, www.itis.gov). If the species name can not be provided, this should be the lowest level taxonomic rank that can be determined and that is used in the ITIS taxonomy. Additional information can be provided using the term "taxon detail".
example: Buteo swainsoni
same as: species, individual taxon canonical name

attachment type: The way a tag is attached to an animal. Values are chosen from a controlled list:
collar: The tag is attached by a collar around the animal's neck.
glue: The tag is attached to the animal using glue.
harness: The tag is attached to the animal using a harness.
implant: The tag is placed under the skin of the an animal.
tape: The tag is attached to the animal using tape.
other: user specified

data processing software: Name of the software program/s, scripts, etc. used to process raw sensor data and derive location estimates.
example: BASTrack

deploy off latitude: The geographic latitude of the location where the deployment ended (intended primarily for instances in which the animal release and tag retrieval locations have higher accuracy than those derived from sensor data).
example: -38.6866
units: decimal degrees, WGS84 reference system

deploy off longitude: The geographic longitude of the location where the deployment ended (intended primarily for instances in which the animal release and tag retrieval locations have higher accuracy than those derived from sensor data).
example: 146.3104
units: decimal degrees, WGS84 reference system

deploy off timestamp: The timestamp when the tag deployment ended.
example: 2009-10-01 12:00:00.000
format: yyyy-MM-dd HH:mm:ss.sss
units: UTC or GPS time, which is a few leap seconds different from UTC
same as: deploy off date

deploy on latitude: The geographic latitude of the location where the animal was released (intended primarily for instances in which the animal release and tag retrieval locations have higher accuracy than those derived from sensor data).
example: 27.3516
units: decimal degrees, WGS84 reference system

deploy on longitude: The geographic longitude of the location where the animal was released (intended primarily for instances in which the animal release and tag retrieval locations have higher accuracy than those derived from sensor data).
example: -97.3321
units: decimal degrees, WGS84 reference system

deploy on timestamp: The timestamp when the tag deployment started.
example: 2008-08-30 18:00:00.000
format: yyyy-MM-dd HH:mm:ss.sss
units: UTC or GPS time, which is a few leap seconds different from UTC
same as: deploy on date

deployment comments: Additional information about the tag deployment that is not described by other reference data terms.
example: body length 154 cm; condition good

deployment end comments: a description of the end of a tag deployment, such as cause of mortality or notes on the removal and/or failure of tag.
example: Data transmission stopped after 108 days. Cause unknown.

deployment end type: A categorical classification of the tag deployment end. Values are chosen from a controlled list:
captured: The tag remained on the animal but the animal was captured or confined.
dead: The deployment ended with the death of the animal that was carrying the tag.
equipment failure: The tag stopped working.
fall off: The attachment of the tag to the animal failed, and it fell of accidentally.
other
released: The tag remained on the animal but the animal was released from captivity or confinement.
removal: The tag was purposefully removed from the animal.
unknown: The deployment ended by an unknown cause.

deployment ID: A unique identifier for the deployment of a tag on animal, provided by the data owner. If the data owner does not provide a Deployment ID, an internal Movebank deployment identifier may sometimes be shown.
example: Jane-Tag42

duty cycle: Remarks associated with the duty cycle of a tag during the deployment, describing the times it is on/off and the frequency at which it transmits or records data. Units and time zones should be defined in the remarks.
example: 15-min fixes from 8:00-18:00 local time (0:00-10:00 UTC)

event ID: An identifier for the set of values associated with each event, i.e. sensor measurement. A unique event ID is assigned to every time-location or other time-measurement record in Movebank. If multiple measurements are included within a single row of a data file, they will share an event ID. If users import the same sensor measurement to Movebank multiple times, a separate event ID will be assigned to each.
example: 6340565
units: none

location lat: The geographic longitude of the location as estimated by the sensor. Positive values are east of the Greenwich Meridian, negative values are west of it.
example: -121.1761111
units: decimal degrees, WGS84 reference system

location long: The geographic longitude of the location as estimated by the sensor. Positive values are east of the Greenwich Meridian, negative values are west of it.
example: -121.1761111
units: decimal degrees, WGS84 reference system
same as: location long

manipulation type: The way in which the animal was manipulated during the deployment. Additional details about the manipulation can be provided using "manipulation comments". Values are chosen from a controlled list:
confined: The animal's movement was restricted to within a defined area.
none: The animal received no treatment other than the tag attachment.
relocated: The animal was released from a site other than the one at which it was captured.
manipulated other: The animal was manipulated in some other way, such as a physiological manipulation.

sensor type: The type of sensor with which data were collected. All sensors are associated with a tag id, and tags can contain multiple sensor types. Values are chosen from a controlled list:
acceleration: The sensor collects acceleration data.
accessory measurements: The sensor collects accessory measurements, such as battery voltage.
Argos Doppler shift: The sensor is using Argos Doppler shift for determining position.
barometer: The sensor records air or water pressure.
bird ring: The animal is identified by a ring that has a unique ID.
GPS: The sensor uses GPS to find location and stores these.
magnetometer: The sensor records the magnetic field.
natural mark: The animal is identified by a natural marking.
radio transmitter: The sensor is a classical radio transmitter.
solar geolocator: The sensor collects light levels, which are used to determine position (for processed locations).
solar geolocator raw: The sensor collects light levels, which are used to determine position (for raw light-level measurements).

study name: The name of the study in Movebank.

study site: A location such as the deployment site or colony, or a location-related group such as the herd or pack name.
example: Pickerel Island North

tag ID: A unique identifier for the tag, provided by the data owner. If the data owner does not provide a tag ID, an internal Movebank tag identifier may sometimes be shown.
example: 2342
same as: tag local identifier

tag manufacturer name: The company or person that produced the tag.
example: Holohil

tag readout method: The way the data are received from the tag. Values are chosen from a controlled list:
satellite: Data are transferred via satellite.
phone network: Data are transferred via a phone network, such as GSM or AMPS.
other wireless: Data are transferred via another form of wireless data transfer, such as a VHF radio transmitter/receiver.
tag retrieval: The tag must be physically retrieved in order to obtain the data.

temperature external: The temperature measured by the tag (different from ambient temperature or internal body temperature of the animal).
example: 32.1
units: degrees Celsius

timestamp: The date and time a sensor measurement was taken.
example: 2008-08-14 18:31:00.000
format: yyyy-MM-dd HH:mm:ss.sss
units: UTC or GPS time, which is a few leap seconds different from UTC

visible: Determines whether an event is visible on the Movebank Search Map. Values are calculated automatically, with TRUE indicating the event has not been flagged as an outlier by "algorithm marked outlier", "import marked outlier" or "manually marked outlier", or that the user has overridden the results of these outlier attributes using "manually marked valid" = TRUE. Allowed values are TRUE or FALSE.

-----------

More Information
For more information about this repository, see www.movebank.org/node/15294, the FAQ at www.movebank.org/node/2220, or contact us at support@movebank.org.