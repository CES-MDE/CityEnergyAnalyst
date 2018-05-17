var map;

/**
 * Zoom in on the map for the input...
 */
$(document).ready(function() {
    $.getJSON('http://localhost:5050/inputs/geojson/zone', function(geojson){
        console.log(geojson.bbox);
        bbox = L.latLng([
            (geojson.bbox[1] + geojson.bbox[3]) / 2,
            (geojson.bbox[0] + geojson.bbox[2]) / 2]);
        map = L.map('mapid').setView(bbox, 16);
        L.tileLayer('http://{s}.tile.osm.org/{z}/{x}/{y}.png',
            {attribution: "Data copyright OpenStreetMap contributors"}).addTo(map);
        L.geoJSON(geojson, {
            onEachFeature: function onEachFeature(feature, layer) {
                layer.on('click', function (e) {
                    console.log(e);
                    console.log(e.target.feature.properties.Name);
                });
            }
        }).addTo(map)
    });
});