"""Tracked cities: live data is fetched and forecasts are produced for these.

`cpcb_area` is the spelling used in the CPCB file; `kaggle` is the 5-city Kaggle file prefix.
Coordinates are city centres (used for Open-Meteo requests and the map).
"""
from dataclasses import dataclass
from typing import Optional

from .common import slugify


@dataclass(frozen=True)
class City:
    name: str
    state: str
    lat: float
    lon: float
    cpcb_area: Optional[str] = None
    kaggle: Optional[str] = None

    @property
    def slug(self) -> str:
        return slugify(self.name)


CITIES = [
    City("Delhi", "Delhi", 28.6139, 77.2090, "Delhi", "Delhi"),
    City("Mumbai", "Maharashtra", 19.0760, 72.8777, "Mumbai", "Mumbai"),
    City("Bengaluru", "Karnataka", 12.9716, 77.5946, "Bengaluru", "Bangalore"),
    City("Hyderabad", "Telangana", 17.3850, 78.4867, "Hyderabad", "Hyderabad"),
    City("Chennai", "Tamil Nadu", 13.0827, 80.2707, "Chennai", "Chennai"),
    City("Kolkata", "West Bengal", 22.5726, 88.3639, "Kolkata"),
    City("Lucknow", "Uttar Pradesh", 26.8467, 80.9462, "Lucknow"),
    City("Kanpur", "Uttar Pradesh", 26.4499, 80.3319, "Kanpur"),
    City("Varanasi", "Uttar Pradesh", 25.3176, 82.9739, "Varanasi"),
    City("Agra", "Uttar Pradesh", 27.1767, 78.0081, "Agra"),
    City("Prayagraj", "Uttar Pradesh", 25.4358, 81.8463, "Prayagraj"),
    City("Noida", "Uttar Pradesh", 28.5355, 77.3910, "NOIDA"),
    City("Ghaziabad", "Uttar Pradesh", 28.6692, 77.4538, "Ghaziabad"),
    City("Meerut", "Uttar Pradesh", 28.9845, 77.7064, "Meerut"),
    City("Gurugram", "Haryana", 28.4595, 77.0266, "Gurugram"),
    City("Rohtak", "Haryana", 28.8955, 76.6066, "Rohtak"),
    City("Patna", "Bihar", 25.5941, 85.1376, "Patna"),
    City("Muzaffarpur", "Bihar", 26.1209, 85.3647, "Muzaffarpur"),
    City("Gaya", "Bihar", 24.7914, 85.0002, "Gaya"),
    City("Jaipur", "Rajasthan", 26.9124, 75.7873, "Jaipur"),
    City("Jodhpur", "Rajasthan", 26.2389, 73.0243, "Jodhpur"),
    City("Chandigarh", "Chandigarh", 30.7333, 76.7794, "Chandigarh"),
    City("Ludhiana", "Punjab", 30.9010, 75.8573, "Ludhiana"),
    City("Amritsar", "Punjab", 31.6340, 74.8723, "Amritsar"),
    City("Jalandhar", "Punjab", 31.3260, 75.5762, "Jalandhar"),
    City("Patiala", "Punjab", 30.3398, 76.3869, "Patiala"),
    City("Bathinda", "Punjab", 30.2110, 74.9455, "Bathinda"),
    City("Dehradun", "Uttarakhand", 30.3165, 78.0322, "Dehradun"),
    City("Ahmedabad", "Gujarat", 23.0225, 72.5714, "Ahmedabad"),
    City("Surat", "Gujarat", 21.1702, 72.8311, "Surat"),
    City("Pune", "Maharashtra", 18.5204, 73.8567, "Pune"),
    City("Nagpur", "Maharashtra", 21.1458, 79.0882, "Nagpur"),
    City("Bhopal", "Madhya Pradesh", 23.2599, 77.4126, "Bhopal"),
    City("Indore", "Madhya Pradesh", 22.7196, 75.8577, "Indore"),
    City("Raipur", "Chhattisgarh", 21.2514, 81.6296, "Raipur"),
    City("Visakhapatnam", "Andhra Pradesh", 17.6868, 83.2185, "Visakhapatnam"),
    City("Guwahati", "Assam", 26.1445, 91.7362, "Guwahati"),
    City("Thiruvananthapuram", "Kerala", 8.5241, 76.9366, "Thiruvananthapuram"),
    City("Coimbatore", "Tamil Nadu", 11.0168, 76.9558, "Coimbatore"),
]

BY_NAME = {c.name: c for c in CITIES}
BY_SLUG = {c.slug: c for c in CITIES}
