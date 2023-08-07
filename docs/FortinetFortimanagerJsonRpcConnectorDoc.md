## About the connector
The Fortinet FortiManager JSON RPC Connector is an advanced connector with freeform actions to use the JSON-RPC API directly. This connector puts the onus on the user to understand the FortiManager API. To use the connector that simplify actions please see the original Fortinet FortiManager Connector.
<p>This document provides information about the Fortinet FortiManager JSON RPC Connector, which facilitates automated interactions, with a Fortinet FortiManager JSON RPC server using FortiSOAR&trade; playbooks. Add the Fortinet FortiManager JSON RPC Connector as a step in FortiSOAR&trade; playbooks and perform automated operations with Fortinet FortiManager JSON RPC.</p>
### Version information

Connector Version: 1.0.0


Authored By: Fortinet CSE

Certified: No
## Release Notes for version 1.0.0
Following enhancements have been made to the Fortinet FortiManager JSON RPC Connector in version 1.0.0:
<ul>
<li><p>Added the following new operations:</p>

<ul>
<li>JSON RPC Add</li>
<li>JSON RPC Set</li>
<li>JSON RPC Get</li>
<li>JSON RPC Exec</li>
<li>JSON RPC Delete</li>
</ul></li>
</ul>

<p>This connector puts the onus on the user to understand the FMG API that can be found in the <a href="https://fndn.fortinet.net/index.php?/fortiapi/5-fortimanager/">FNDN FortiAPI</a> to use. To use the connector that simplify actions please see the original <a href="https://fortisoar.contenthub.fortinet.com//list.html?contentType=connector&searchContent=Fortinet%20FortiManager">Fortinet Fortimanager Connector</a>.</p>
## Installing the connector
<p>Use the <strong>Content Hub</strong> to install the connector. For the detailed procedure to install a connector, click <a href="https://docs.fortinet.com/document/fortisoar/0.0.0/installing-a-connector/1/installing-a-connector" target="_top">here</a>.</p><p>You can also use the <code>yum</code> command as a root user to install the connector:</p>
<pre>yum install cyops-connector-fortinet-fortimanager-json-rpc</pre>

## Prerequisites to configuring the connector
- You must have the credentials of Fortinet FortiManager JSON RPC server to which you will connect and perform automated operations.
- The FortiSOAR&trade; server should have outbound connectivity to port 443 on the Fortinet FortiManager JSON RPC server.

## Minimum Permissions Required
- Not applicable

## Configuring the connector
For the procedure to configure a connector, click [here](https://docs.fortinet.com/document/fortisoar/0.0.0/configuring-a-connector/1/configuring-a-connector)
### Configuration parameters
<p>In FortiSOAR&trade;, on the Connectors page, click the <strong>Fortinet FortiManager JSON RPC</strong> connector row (if you are in the <strong>Grid</strong> view on the Connectors page) and in the <strong>Configurations</strong> tab enter the required configuration details:</p>
<table border=1><thead><tr><th>Parameter</th><th>Description</th></tr></thead><tbody><tr><td>Hostname</td><td>IP address or Hostname of the Fortinet FortiManager endpoint server to which you will connect and perform the automated operations.
</td>
</tr><tr><td>Username</td><td>Username with JSON-RPC enabled to access the Fortinet FortiManager server to which you will connect and perform the automated operations.
</td>
</tr><tr><td>Password</td><td>Password to access the Fortinet FortiManager server to which you will connect and perform the automated operations.
</td>
</tr><tr><td>Port</td><td>Port number used to access the Fortinet FortiManager server to which you will connect and perform the automated operations. By default, this is set to 443.
</td>
</tr><tr><td>Verify SSL</td><td>Specifies whether the SSL certificate for the server is to be verified or not. <br/>By default, this option is set to True.</td></tr>
<tr><td>Debug Connection</td><td>Only used with the json_rpc connections, and enables the debug. This can sometimes cause an I/O operation error since debugging involves printing responses, which writes to the integration.log file. 
</td>
</tr><tr><td>Verbose JSON</td><td>Setting this to true adds a verbose flag to the request, so that the integers are translated to the string represntation by Fortimanager.
</td>
</tr></tbody></table>
## Actions supported by the connector
The following automated operations can be included in playbooks and you can also use the annotations to access operations from FortiSOAR&trade; release 4.10.0 and onwards:
<table border=1><thead><tr><th>Function</th><th>Description</th><th>Annotation and Category</th></tr></thead><tbody><tr><td>JSON RPC Add</td><td>A Generic FMG Add action that lets you specify any valid URL and data object</td><td>json_rpc_add <br/>Investigation</td></tr>
<tr><td>JSON RPC Set</td><td>A Generic FMG Set action that lets you specify any valid URL and data object</td><td>json_rpc_set <br/>Investigation</td></tr>
<tr><td>JSON RPC Get</td><td>A Generic FMG Get action that lets you specify any valid URL and data object</td><td>json_rpc_get <br/>Investigation</td></tr>
<tr><td>JSON RPC Exec</td><td>A Generic FMG Execute action that lets you specify any valid URL and data object</td><td>json_rpc_execute <br/>Investigation</td></tr>
<tr><td>JSON RPC Delete</td><td>A Generic FMG Delete action that lets you specify any valid URL and data object</td><td>json_rpc_delete <br/>Investigation</td></tr>
</tbody></table>
### operation: JSON RPC Add
#### Input parameters
<table border=1><thead><tr><th>Parameter</th><th>Description</th></tr></thead><tbody><tr><td>URL</td><td>The url you wish to hit
</td></tr><tr><td>Data</td><td>Pass a json object for the data you want to send. 
</td></tr></tbody></table>
#### Output

 The output contains a non-dictionary value.
### operation: JSON RPC Set
#### Input parameters
<table border=1><thead><tr><th>Parameter</th><th>Description</th></tr></thead><tbody><tr><td>URL</td><td>The url you wish to hit
</td></tr><tr><td>Data</td><td>Pass a json object for the data you want to send. 
</td></tr></tbody></table>
#### Output

 The output contains a non-dictionary value.
### operation: JSON RPC Get
#### Input parameters
<table border=1><thead><tr><th>Parameter</th><th>Description</th></tr></thead><tbody><tr><td>URL</td><td>The url you wish to hit
</td></tr><tr><td>Data</td><td>Pass a json object for the data you want to send. 
</td></tr></tbody></table>
#### Output

 The output contains a non-dictionary value.
### operation: JSON RPC Exec
#### Input parameters
<table border=1><thead><tr><th>Parameter</th><th>Description</th></tr></thead><tbody><tr><td>URL</td><td>The url you wish to hit
</td></tr><tr><td>Data</td><td>Pass a json object for the data you want to send. 
</td></tr><tr><td>Track Task</td><td>Checking this box will attempt to track a task if found, and wait to return the output until that task is complete
</td></tr></tbody></table>
#### Output

 The output contains a non-dictionary value.
### operation: JSON RPC Delete
#### Input parameters
<table border=1><thead><tr><th>Parameter</th><th>Description</th></tr></thead><tbody><tr><td>URL</td><td>The url you wish to hit
</td></tr><tr><td>Data</td><td>Pass a json object for the data you want to send. 
</td></tr></tbody></table>
#### Output

 The output contains a non-dictionary value.
## Included playbooks
The `Sample - fortinet-fortimanager-json-rpc - 1.0.0` playbook collection comes bundled with the Fortinet FortiManager JSON RPC connector. These playbooks contain steps using which you can perform all supported actions. You can see bundled playbooks in the **Automation** > **Playbooks** section in FortiSOAR&trade; after importing the Fortinet FortiManager JSON RPC connector.

- JSON RPC Add
- JSON RPC Delete
- JSON RPC Exec
- JSON RPC Get
- JSON RPC Set

**Note**: If you are planning to use any of the sample playbooks in your environment, ensure that you clone those playbooks and move them to a different collection since the sample playbook collection gets deleted during connector upgrade and delete.
