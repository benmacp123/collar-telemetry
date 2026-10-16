README

This data file is published by the Movebank Data Repository (www.datarepository.movebank.org). As of the time of publication, a version of this published animal tracking dataset can be viewed on Movebank (www.movebank.org) in the study "Black-backed jackal, Etosha National Park, Namibia" (Movebank Study ID 304875150). Individual attributes in the data files are defined below and in the Movebank Attribute Dictionary, available at www.movebank.org/node/2381. This dataset contains the original, complete version of the black-backed jackal data published with DOI 10.5441/001/1.hm5nk220 (see Abrahms et al. [2017] below).

This data package includes the following data files:
Black-backed jackal, Etosha National Park, Namibia.csv
Black-backed jackal, Etosha National Park, Namibia-reference-data.csv
carcassLocations.csv

These data are described in the following written publications:
Borchering RK, Bellan SE, Flynn JM, Pulliam JRC, McKinley SA (2017) Resource-driven encounters and the induction of disease among consumers. Journal of The Royal Society Interface. doi:10.1098/rsif.2017.0555

Abrahms B, Seidel DP, Dougherty E, Hazen EL, Bograd SJ, Wilson AM, McNutt JW, Costa DP, Blake S, Brashares JS, Getz WM (2017) Suite of simple metrics reveals common movement syndromes across vertebrate taxa. Movement Ecology 5:12. doi:10.1186/s40462-017-0104-2. Data are archived in the Movebank Data Repository with DOI 10.5441/001/1.hm5nk220.

Bellan SE, Cizauskas CA, Miyen J, Ebersohn K, Küsters M, Prager KC, Van Vuuren M, Sabeta C, Getz WM (2012) Black-backed jackal exposure to rabies virus, canine distemper virus, and Bacillus anthracis in Etosha National Park, Namibia. Journal of Wildlife Diseases 48(2):371–381. doi:10.7589/0090-3558-48.2.371

Data package citation:
Bellan SE, Getz WM (2017) Data from: Resource-driven encounters and the induction of disease among consumers. Movebank Data Repository. doi:10.5441/001/1.n1r7ds5r

-----------

Terms of Use
This data file is licensed by the Creative Commons Zero (CC0 1.0) license. The intent of this license is to facilitate the re-use of works. The Creative Commons Zero license is a "no rights reserved" license that allows copyright holders to opt out of copyright protections automatically extended by copyright and other laws, thus placing works in the public domain with as little legal restriction as possible. However, works published with this license must still be appropriately cited following professional and ethical standards for academic citation.

We highly recommend that you contact the data creator if possible if you will be re-using or re-analyzing data in this file. Researchers will likely be interested in learning about new uses of their data, might also have important insights about how to properly analyze and interpret their data, and/or might have additional data they would be willing to contribute to your project. Feel free to contact us at support@movebank.org if you need assistance contacting data owners.

See here for the full description of this license
http://creativecommons.org/publicdomain/zero/1.0

-----------

Data Attributes
These definitions come from the Movebank Attribute Dictionary, available at www.movebank.org/node/2381.

animal ID: An individual identifier for the animal, provided by the data owner. This identifier can be a ring number, a name, the same as the associated tag ID, etc. If the data owner does not provide an Animal ID, an internal Movebank animal identifier may sometimes be shown.
	example: 91876A, Gary
	same as: individual-local-identifier

animal mass: The mass of an the animal.
	example: 500
	units: grams

attachment type: The way a tag is attached to an animal. Values are chosen from a controlled list:
	collar: The tag is attached by a collar around the animal's neck.
	glue: The tag is attached to the animal using glue.
	harness: The tag is attached to the animal using a harness.
	implant: The tag is placed under the skin of the an animal.
	tape: The tag is attached to the animal using tape.
	other: user specified

beacon frequency: The frequency of the radio tag or tag retrieval beacon.
	example: 450.5
	units: MHz
	same as: tag beacon frequency

deploy off latitude: The geographic latitude of the location where the deployment ended (intended primarily for instances in which the animal release and tag retrieval locations have higher accuracy than those derived from sensor data).
	example: -38.6866
	units: decimal degrees, WGS84 reference system

deploy off longitude: The geographic longitude of the location where the deployment ended (intended primarily for instances in which the animal release and tag retrieval locations have higher accuracy than those derived from sensor data).
	example: 146.3104
	units: decimal degrees, WGS84 reference system

deploy off timestamp: The timestamp when the tag deployment ended.
	example: 2009-10-01 12:00:00.000
	format: yyyy-MM-dd HH:mm:ss.sss
	units: UTC (Coordinated Universal Time) or GPS time, which is a few leap seconds different from UTC
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
	units: UTC (Coordinated Universal Time) or GPS time, which is a few leap seconds different from UTC
	same as: deploy on date

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

event ID: An identifier for the set of information associated with each record or event in a data set. A unique event ID is assigned to every time-location or other time-measurement record in Movebank.
	example: 6340565
	units: none

latitude (decimal degree): The geographic longitude of a location along an animal track as estimated by the processed sensor data. Positive values are east of the Greenwich Meridian, negative values are west of it.
	example: -121.1761111
	units: decimal degrees, WGS84 reference system
	same as: location lat

life stage: The age class or life stage of the animal at the beginning of the deployment. Can be years or months of age or terms such as "adult", "subadult" and "juvenile". Units should be defined in the values (e.g. "2 years").
	example: juvenile, adult
	units: Any units should be defined in the remarks.

longitude (decimal degree): The geographic longitude of a location along an animal track as estimated by the processed sensor data. Positive values are east of the Greenwich Meridian, negative values are west of it.
	example: -121.1761111
	units: decimal degrees, WGS84 reference system
	same as: location long

manipulation type: The way in which the animal was manipulated during the deployment. Additional details about the manipulation can be provided using manipulation comments. Values are chosen from a controlled list:
	confined: The animal's movement was restricted to within a defined area.
	none: The animal received no treatment other than the tag attachment.
	relocated: The animal was released from a site other than the one at which it was captured.
	manipulated other: The animal was manipulated in some other way, such as a physiological manipulation.

sensor type: The type of sensor with which data were collected. Values are chosen from a controlled list:
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

sex: The sex of the biological individual(s) represented in the Occurrence. Values are from a controlled list:
	m: male
	f: female

study: The name of the study in Movebank in which data are stored.

study site: The name of the deployment site, for example a field station or colony.
	example: Pickerel Island North

tag ID: A unique identifier for the tag, provided by the data owner. If the data owner does not provide a tag ID, an internal Movebank tag identifier may sometimes be shown.
	example: 2342, ptt_4532
	same as: tag local identifier

tag manufacturer name: The company or person that produced the tag.
	example: Holohil
	same as: manufacturer

tag readout method: The way the data are received from the tag. Values are chosen from a controlled list:
	satellite: Data are transferred via satellite.
	phone network: Data are transferred via a phone network, such as GSM or AMPS.
	other wireless: Data are transferred via another form of wireless data transfer, such as a VHF radio transmitter/receiver.
	tag retrieval: The tag must be physically retrieved in order to obtain the data.

taxon: The scientific name of the species on which the tag was deployed, as defined by the Integrated Taxonomic Information System (ITIS, www.itis.gov). If the species name can not be provided, this should be the lowest level taxonomic rank that can be determined and that is used in the ITIS taxonomy. Additional information can be provided using the term taxon detail.
	example: Buteo swainsoni
	same as: species, animal taxon, individual taxon canonical name

timestamp: The date and time a sensor measurement was taken.
	example: 2008-08-14 18:31:00.000
	format: yyyy-MM-dd HH:mm:ss.sss
	units: UTC (Coordinated Universal Time) or GPS time, which is a few leap seconds different from UTC

visible: Determines whether an event is visible on the Movebank Search map. Values are calculated automatically, with FALSE indicating that the event has been marked as an outlier by manually marked outlier or algorithm marked outlier. Allowed values are TRUE or FALSE.

-----------

Data Attributes for "carcassLocations.csv"

These definitions are specific to this original data file from the author. Duplicate entries were removed and only carcasses with the field "scavmov" set to 1 were included. "scavmov" indicates whether or not the carcass should be considered with the jackal location data. One reason why a carcass should not be considered with the jackal location data is if it was known that the carcass was moved or removed for research purposes. In the raw data some of the jackal counts values included comments or were at some point converted to dates. These values were converted back to the numeric value indicated in the final "jackalCount" field. The primary date "date" was chosen to be the date that the carcass was recorded to match with the date the the number of jackals at the carcass was observed. Test results for the presence of anthrax, field "BAPos", were established via selective culture with PCR confirmation.

date: The date that the carcass was recorded.

long: The longitude value of the GPS coordinate.

lat: The latitude value of the GPS coordinate.

species: Indicates the species of the carcass. Key:
AM - springbok (Antidorcas marsupialis)
AMP - black-faced impala (Aepyceros melampus petersi)
CC - spotted hyena (Crocuta crocuta) 
CM -  jackal (Canis mesomelas)
CT - blue wildebeest (Connochaetes taurinus)
DB, Dbb, DBB - black rhino (Diceros bicornis bicornis)
EQ -  plains zebra (Equus quagga) (formerly Equus burchelli)
GC -  giraffe (Giraffa camelopardalis) 
GG - common genet (Genetta genetta)
LA - elephant (Loxodonta africanus)
MC - honey badger (Mellivora capensis)
OG - gemsbok (Oryx gazella)
OM - bat-eared fox (Otocyon megalotis)
PA - warthog (Phacochoerus africanus)
PL - lion (Panthera leo)
RC - steenbok (Raphicerus campestris)
SC - ostrich (Struthio camelus)
TO - eland (Taurotragus oryx)
TS - greater kudu (Tragelaphus strepsiceros)
UNK - unknown

BAPos: Indicates if there was a positive, negative, or undetermined test result for the presence anthrax causing bacteria. This value was not recorded for all carcasses.

jackalCount: number of jackals seen at the carcass when the carcass was recorded. This value was not recorded for all carcasses.

-----------

More Information
For more information about this repository, see www.movebank.org/node/15294, the FAQ at www.movebank.org/node/2220, or contact us at support@movebank.org.