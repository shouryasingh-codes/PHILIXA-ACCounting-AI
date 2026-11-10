"""Generate a Store manifest only from owner-verified Partner Center metadata."""
import json
from pathlib import Path
import re
import xml.etree.ElementTree as ET


def manifest(metadata):
    required = ('name', 'publisher', 'product_id', 'publisher_display_name')
    if metadata.get('partner_center_verified') is not True:
        raise ValueError('Owner-verified Partner Center identity required; release withheld')
    if any(not isinstance(metadata.get(k), str) or not metadata[k].strip() for k in required):
        raise ValueError('Partner Center identity incomplete')
    if not re.fullmatch(r'[A-Za-z0-9.-]{3,50}', metadata['name']):
        raise ValueError('Package identity invalid')
    if not re.fullmatch(r'[A-Z0-9]{12}', metadata['product_id']):
        raise ValueError('Store product ID invalid')
    if not metadata['publisher'].startswith('CN=') or any(
            token in metadata['publisher'].lower() for token in ('placeholder', 'example')):
        raise ValueError('Verified publisher required')
    from helper.runtime import VERSION
    ns = 'http://schemas.microsoft.com/appx/manifest/foundation/windows10'
    uap = 'http://schemas.microsoft.com/appx/manifest/uap/windows10'
    desktop = 'http://schemas.microsoft.com/appx/manifest/desktop/windows10'
    restricted = 'http://schemas.microsoft.com/appx/manifest/foundation/windows10/restrictedcapabilities'
    for prefix, value in (('', ns), ('uap', uap), ('desktop', desktop), ('rescap', restricted)):
        ET.register_namespace(prefix, value)
    root = ET.Element('{'+ns+'}Package', IgnorableNamespaces='uap desktop rescap')
    def node(parent, name, **attrs):
        return ET.SubElement(parent, '{'+ns+'}'+name, attrs)
    node(root, 'Identity', Name=metadata['name'], Publisher=metadata['publisher'],
         Version=VERSION+'.0', ProcessorArchitecture='x64')
    properties = node(root, 'Properties')
    for name, value in (('DisplayName','Philixa Tally Connector'),
                        ('PublisherDisplayName',metadata['publisher_display_name']),
                        ('Logo','Assets/StoreLogo.png')):
        node(properties, name).text = value
    dependencies = node(root, 'Dependencies')
    node(dependencies, 'TargetDeviceFamily', Name='Windows.Desktop',
         MinVersion='10.0.19045.0', MaxVersionTested='10.0.19045.0')
    resources = node(root, 'Resources'); node(resources, 'Resource', Language='en-US')
    apps = node(root, 'Applications')
    app = node(apps, 'Application', Id='Philixa', Executable='app/PhilixaConnect.exe',
               EntryPoint='Windows.FullTrustApplication')
    ET.SubElement(app, '{'+uap+'}VisualElements', DisplayName='Philixa Tally Connector',
                  Description='Connect your Tally PC with Philixa', BackgroundColor='#236548',
                  Square150x150Logo='Assets/Square150x150Logo.png',
                  Square44x44Logo='Assets/Square44x44Logo.png')
    extensions = node(app, 'Extensions')
    extension = ET.SubElement(extensions, '{'+desktop+'}Extension',
                             Category='windows.startupTask', Executable='app/PhilixaConnect.exe',
                             EntryPoint='Windows.FullTrustApplication')
    ET.SubElement(extension, '{'+desktop+'}StartupTask', TaskId='PhilixaStartup',
                  Enabled='true', DisplayName='Philixa Tally Connector')
    caps = node(root, 'Capabilities')
    ET.SubElement(caps, '{'+restricted+'}Capability', Name='runFullTrust')
    return ET.tostring(root, encoding='unicode', xml_declaration=True)


if __name__ == '__main__':
    import sys
    source, target = map(Path, sys.argv[1:3])
    target.write_text(manifest(json.loads(source.read_text(encoding='utf-8'))), encoding='utf-8')
