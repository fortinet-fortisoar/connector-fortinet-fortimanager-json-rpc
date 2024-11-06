#### What's Improved

Following enhancements have been made to the Fortinet FortiManager JSON RPC Connector in version 1.0.6: 

- Support for authenticating to FMG with an API Key
- Support for new pyFMG track task parameters
- New implicit handling for special case operations in FMG that always require more than one API call to complete an action
  - This is like a smart handling function to do what would naturally come next. If users requests for A, the connector will also ask for B once A is complete


